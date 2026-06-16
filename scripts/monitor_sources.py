#!/usr/bin/env python3
"""Monitor official red-flag source endpoints for new downloadable sources."""

from __future__ import annotations

import argparse
import csv
from datetime import UTC, datetime
import json
import logging
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
import xml.etree.ElementTree as ET

import yaml
from bs4 import BeautifulSoup

from build_registry import DEFAULT_REGISTRY_PATH, DEFAULT_SOURCES_YAML_PATH, normalize_url
from harvest_sources import USER_AGENT
from pipeline import download_sources

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from redflag_mcp.config import URL_DOMAIN_TO_REGULATOR, regulator_from_url  # noqa: E402

RED_FLAG_SOURCES_DIR = PROJECT_ROOT / "red_flag_sources"
SOURCE_FILE_CATALOGUE_DIR = RED_FLAG_SOURCES_DIR / "source_file_catalogue"
DEFAULT_REPORT_DIR = SOURCE_FILE_CATALOGUE_DIR / "monitoring_runs"
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class MonitoringPaths:
    catalogue_dir: Path = SOURCE_FILE_CATALOGUE_DIR
    source_inventory: Path = SOURCE_FILE_CATALOGUE_DIR / "source_inventory.csv"
    subscription_automation: Path = SOURCE_FILE_CATALOGUE_DIR / "subscription_automation.csv"
    prioritization_ranking: Path = SOURCE_FILE_CATALOGUE_DIR / "prioritization_ranking.csv"
    hidden_sources: Path = SOURCE_FILE_CATALOGUE_DIR / "hidden_sources.csv"


@dataclass(frozen=True)
class SetupGap:
    path: Path
    message: str


@dataclass(frozen=True)
class MonitoringEndpoint:
    organization: str
    jurisdiction: str
    publication_page: str
    publication_types: str
    relevant_categories: str
    monitoring_priority: str
    feed_type: str
    subscription_url: str
    rank: int | None
    tier: int | None

    @property
    def collection_method(self) -> str:
        feed_type = self.feed_type.lower()
        subscription_url = self.subscription_url.strip()
        if subscription_url.lower() == "unspecified":
            return "html"
        if "rss" in feed_type:
            return "rss"
        if "atom" in feed_type:
            return "atom"
        if "json" in feed_type or "api" in feed_type or "open data" in feed_type:
            return "structured"
        if "xml" in feed_type:
            return "xml"
        return "html"


@dataclass(frozen=True)
class MonitoringSources:
    endpoints: list[MonitoringEndpoint] = field(default_factory=list)
    setup_gaps: list[SetupGap] = field(default_factory=list)


class CandidateSource(str, Enum):
    ENDPOINT = "endpoint"
    TAVILY = "tavily"


@dataclass(frozen=True)
class CandidateURL:
    organization: str
    endpoint_url: str
    url: str
    title: str = ""
    published_at: str = ""
    source: CandidateSource = CandidateSource.ENDPOINT


@dataclass(frozen=True)
class CollectionFailure:
    organization: str
    endpoint_url: str
    message: str


@dataclass(frozen=True)
class CollectionResult:
    candidates: list[CandidateURL] = field(default_factory=list)
    failures: list[CollectionFailure] = field(default_factory=list)


@dataclass(frozen=True)
class CandidateRejection:
    url: str
    reason: str


@dataclass(frozen=True)
class TavilyImportResult:
    candidates: list[CandidateURL] = field(default_factory=list)
    rejections: list[CandidateRejection] = field(default_factory=list)


@dataclass(frozen=True)
class CandidateSelection:
    new_candidates: list[CandidateURL] = field(default_factory=list)
    duplicate_candidates: list[CandidateURL] = field(default_factory=list)


@dataclass(frozen=True)
class CandidateDownloadFailure:
    url: str
    reason: str


@dataclass(frozen=True)
class CandidateDownloadResult:
    downloaded: list[dict[str, Any]] = field(default_factory=list)
    duplicates: list[CandidateURL] = field(default_factory=list)
    failures: list[CandidateDownloadFailure] = field(default_factory=list)


@dataclass(frozen=True)
class MonitoringRunResult:
    summary: dict[str, int | bool]
    setup_gaps: list[SetupGap] = field(default_factory=list)
    candidates: list[CandidateURL] = field(default_factory=list)
    duplicates: list[CandidateURL] = field(default_factory=list)
    collection_failures: list[CollectionFailure] = field(default_factory=list)
    tavily_rejections: list[CandidateRejection] = field(default_factory=list)
    downloaded: list[dict[str, Any]] = field(default_factory=list)
    download_failures: list[CandidateDownloadFailure] = field(default_factory=list)
    report_path: Path | None = None


SOURCE_INVENTORY_COLUMNS = {
    "Organization",
    "Jurisdiction",
    "Link",
    "Publication Page",
    "Publication Types",
    "Update Frequency",
    "RSS Available (Yes/No)",
    "Email Subscription Available (Yes/No)",
    "API Available (Yes/No)",
    "Historical Archive (Yes/No)",
    "Relevant Categories",
    "Monitoring Priority",
}

SUBSCRIPTION_COLUMNS = {
    "Organization",
    "Feed Type (RSS/Email/API/XML/Open data)",
    "Exact Subscription URL",
    "Authentication Required (Yes/No)",
    "Update Frequency",
    "Notes",
}

PRIORITIZATION_COLUMNS = {
    "Rank",
    "Organization",
    "Jurisdiction",
    "Primary Risk Signals (list)",
    "Rationale",
    "Tier (1/2/3)",
}

HIDDEN_SOURCE_COLUMNS = {
    "Organization/Consortium",
    "Jurisdiction",
    "Link",
    "Publication Types",
    "Relevance",
    "Notes",
}


def _load_required_csv(path: Path, required_columns: set[str]) -> tuple[list[dict[str, str]], list[SetupGap]]:
    if not path.exists():
        return [], [SetupGap(path, "missing required CSV")]
    if path.stat().st_size == 0:
        return [], [SetupGap(path, "empty required CSV")]

    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = set(reader.fieldnames or [])
        missing = sorted(required_columns - fieldnames)
        if missing:
            return [], [SetupGap(path, f"missing required columns: {', '.join(missing)}")]
        rows = [{key: value or "" for key, value in row.items()} for row in reader]

    return rows, []


def _parse_int(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def load_monitoring_sources(paths: MonitoringPaths = MonitoringPaths()) -> MonitoringSources:
    setup_gaps: list[SetupGap] = []

    inventory_rows, gaps = _load_required_csv(paths.source_inventory, SOURCE_INVENTORY_COLUMNS)
    setup_gaps.extend(gaps)
    subscription_rows, gaps = _load_required_csv(paths.subscription_automation, SUBSCRIPTION_COLUMNS)
    setup_gaps.extend(gaps)
    priority_rows, gaps = _load_required_csv(paths.prioritization_ranking, PRIORITIZATION_COLUMNS)
    setup_gaps.extend(gaps)
    _hidden_rows, gaps = _load_required_csv(paths.hidden_sources, HIDDEN_SOURCE_COLUMNS)
    setup_gaps.extend(gaps)

    if setup_gaps:
        return MonitoringSources(setup_gaps=setup_gaps)

    subscriptions_by_org = {
        row["Organization"].strip(): row
        for row in subscription_rows
        if row.get("Organization", "").strip()
    }
    inventory_by_org = {
        row["Organization"].strip(): row
        for row in inventory_rows
        if row.get("Organization", "").strip()
    }
    unmatched_priority_organizations: list[str] = []
    for priority in priority_rows:
        priority_organization = priority.get("Organization", "").strip()
        if not priority_organization:
            continue
        if not any(_priority_matches_inventory(inventory_org, priority_organization) for inventory_org in inventory_by_org):
            unmatched_priority_organizations.append(priority_organization)

    for organization in sorted(unmatched_priority_organizations):
        setup_gaps.append(
            SetupGap(
                paths.prioritization_ranking,
                f"priority organization has no source inventory row: {organization}",
            )
        )

    endpoints: list[MonitoringEndpoint] = []
    for organization, inventory in inventory_by_org.items():
        subscription = subscriptions_by_org.get(organization, {})
        priority = _priority_for_inventory_organization(organization, priority_rows)
        endpoints.append(
            MonitoringEndpoint(
                organization=organization,
                jurisdiction=inventory.get("Jurisdiction", ""),
                publication_page=inventory.get("Publication Page", ""),
                publication_types=inventory.get("Publication Types", ""),
                relevant_categories=inventory.get("Relevant Categories", ""),
                monitoring_priority=inventory.get("Monitoring Priority", ""),
                feed_type=subscription.get("Feed Type (RSS/Email/API/XML/Open data)", ""),
                subscription_url=subscription.get("Exact Subscription URL", "Unspecified"),
                rank=_parse_int(priority.get("Rank", "")),
                tier=_parse_int(priority.get("Tier (1/2/3)", "")),
            )
        )

    endpoints.sort(key=lambda endpoint: (endpoint.tier or 99, endpoint.rank or 9999, endpoint.organization))
    return MonitoringSources(endpoints=endpoints, setup_gaps=setup_gaps)


def _priority_matches_inventory(inventory_organization: str, priority_organization: str) -> bool:
    inventory_normalized = inventory_organization.lower().strip()
    priority_normalized = priority_organization.lower().strip()
    if inventory_normalized == priority_normalized:
        return True
    return priority_normalized.startswith(f"{inventory_normalized} ")


def _priority_for_inventory_organization(
    organization: str,
    priority_rows: list[dict[str, str]],
) -> dict[str, str]:
    for priority in priority_rows:
        if _priority_matches_inventory(organization, priority.get("Organization", "")):
            return priority
    return {}


def endpoint_url(endpoint: MonitoringEndpoint) -> str:
    if endpoint.subscription_url.strip().lower() != "unspecified":
        return endpoint.subscription_url.strip()
    return endpoint.publication_page.strip()


def collect_endpoint_candidates(endpoint: MonitoringEndpoint, client: Any | None = None) -> CollectionResult:
    url = endpoint_url(endpoint)
    if not url:
        return CollectionResult(
            failures=[
                CollectionFailure(
                    organization=endpoint.organization,
                    endpoint_url="",
                    message="missing endpoint URL",
                )
            ]
        )

    owns_client = client is None
    active_client = client
    if active_client is None:
        import httpx

        active_client = httpx.Client(headers={"User-Agent": USER_AGENT})

    try:
        response = active_client.get(url, follow_redirects=True, timeout=30.0)
        response.raise_for_status()
        method = endpoint.collection_method
        if method in {"rss", "atom", "xml"}:
            candidates = _parse_xml_candidates(endpoint, url, response.text)
        elif method == "structured":
            candidates = _parse_json_candidates(endpoint, url, response)
        else:
            final_url = str(getattr(response, "url", url))
            candidates = _parse_html_candidates(endpoint, url, final_url, response.text)
        return CollectionResult(candidates=candidates)
    except Exception as exc:
        return CollectionResult(
            failures=[
                CollectionFailure(
                    organization=endpoint.organization,
                    endpoint_url=url,
                    message=str(exc),
                )
            ]
        )
    finally:
        if owns_client and active_client is not None:
            active_client.close()


def _parse_xml_candidates(endpoint: MonitoringEndpoint, endpoint_url_value: str, text: str) -> list[CandidateURL]:
    root = ET.fromstring(text)
    candidates: list[CandidateURL] = []
    for item in root.findall(".//item"):
        link = _child_text(item, "link")
        if not link:
            continue
        candidates.append(
            CandidateURL(
                organization=endpoint.organization,
                endpoint_url=endpoint_url_value,
                url=link,
                title=_child_text(item, "title"),
                published_at=_child_text(item, "pubDate"),
            )
        )

    if candidates:
        return candidates

    for entry in root.findall(".//{*}entry"):
        link = ""
        link_element = entry.find("{*}link")
        if link_element is not None:
            link = link_element.attrib.get("href", "") or (link_element.text or "")
        if not link:
            continue
        candidates.append(
            CandidateURL(
                organization=endpoint.organization,
                endpoint_url=endpoint_url_value,
                url=link.strip(),
                title=_child_text(entry, "title"),
                published_at=_child_text(entry, "updated") or _child_text(entry, "published"),
            )
        )
    return candidates


def _child_text(element: ET.Element, tag: str) -> str:
    child = element.find(tag) or element.find(f"{{*}}{tag}")
    if child is None or child.text is None:
        return ""
    return child.text.strip()


def _parse_json_candidates(endpoint: MonitoringEndpoint, endpoint_url_value: str, response: Any) -> list[CandidateURL]:
    try:
        payload = response.json()
    except Exception:
        payload = json.loads(response.text)

    candidates: list[CandidateURL] = []
    for obj in _walk_json_objects(payload):
        url = _first_present(obj, ("url", "link", "href", "download_url", "downloadUrl"))
        if not url or not str(url).startswith(("http://", "https://")):
            continue
        candidates.append(
            CandidateURL(
                organization=endpoint.organization,
                endpoint_url=endpoint_url_value,
                url=str(url),
                title=str(_first_present(obj, ("title", "name", "label")) or ""),
                published_at=str(_first_present(obj, ("date", "published", "published_at", "updated")) or ""),
            )
        )
    return candidates


def _walk_json_objects(value: Any) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    if isinstance(value, dict):
        objects.append(value)
        for child in value.values():
            objects.extend(_walk_json_objects(child))
    elif isinstance(value, list):
        for child in value:
            objects.extend(_walk_json_objects(child))
    return objects


def _first_present(obj: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if obj.get(key):
            return obj[key]
    return None


def _parse_html_candidates(
    endpoint: MonitoringEndpoint,
    endpoint_url_value: str,
    final_url: str,
    text: str,
) -> list[CandidateURL]:
    soup = BeautifulSoup(text, "html.parser")
    allowed_domain = urlparse(final_url or endpoint_url_value).netloc
    seen: set[str] = set()
    candidates: list[CandidateURL] = []
    for anchor in soup.find_all("a"):
        href = anchor.get("href")
        if not href:
            continue
        candidate_url = urljoin(final_url or endpoint_url_value, href)
        parsed = urlparse(candidate_url)
        if parsed.scheme not in {"http", "https"}:
            continue
        if parsed.netloc != allowed_domain:
            continue
        if candidate_url in seen:
            continue
        seen.add(candidate_url)
        candidates.append(
            CandidateURL(
                organization=endpoint.organization,
                endpoint_url=endpoint_url_value,
                url=candidate_url,
                title=anchor.get_text(" ", strip=True),
            )
        )
    return candidates


def import_tavily_candidates(
    results: list[dict[str, Any]],
    endpoints: list[MonitoringEndpoint],
) -> TavilyImportResult:
    inventory_domains = _inventory_domains(endpoints)
    candidates: list[CandidateURL] = []
    rejections: list[CandidateRejection] = []

    for result in results:
        raw_url = str(result.get("url") or result.get("link") or "").strip()
        if not raw_url:
            rejections.append(CandidateRejection(url="", reason="missing URL"))
            continue
        parsed = urlparse(raw_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            rejections.append(CandidateRejection(url=raw_url, reason="invalid URL"))
            continue

        regulator = regulator_from_url(raw_url)
        organization = regulator or inventory_domains.get(parsed.netloc)
        if organization is None:
            rejections.append(
                CandidateRejection(
                    url=raw_url,
                    reason="not an official regulator domain",
                )
            )
            continue

        candidates.append(
            CandidateURL(
                organization=organization,
                endpoint_url="tavily",
                url=raw_url,
                title=str(result.get("title") or ""),
                source=CandidateSource.TAVILY,
            )
        )

    return TavilyImportResult(candidates=candidates, rejections=rejections)


def load_tavily_results_file(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("results"), list):
        return [item for item in payload["results"] if isinstance(item, dict)]
    raise ValueError("Tavily results file must be a JSON list or an object with a 'results' list")


def _inventory_domains(endpoints: list[MonitoringEndpoint]) -> dict[str, str]:
    domains: dict[str, str] = {}
    for endpoint in endpoints:
        for url in (endpoint.publication_page, endpoint.subscription_url):
            if not url or url.strip().lower() == "unspecified":
                continue
            domain = urlparse(url).netloc
            if domain and domain not in URL_DOMAIN_TO_REGULATOR:
                domains[domain] = endpoint.organization
    return domains


def load_known_urls(
    registry_csv: Path = DEFAULT_REGISTRY_PATH,
    sources_yaml: Path = DEFAULT_SOURCES_YAML_PATH,
) -> set[str]:
    known: set[str] = set()
    if registry_csv.exists():
        with registry_csv.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("source_url"):
                    known.add(normalize_url(row["source_url"]))

    if sources_yaml.exists():
        with sources_yaml.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if isinstance(data, dict):
            for entry in data.values():
                if isinstance(entry, dict) and entry.get("url"):
                    known.add(normalize_url(str(entry["url"])))
                elif isinstance(entry, str):
                    known.add(normalize_url(entry))

    return known


def deduplicate_candidates(
    candidates: list[CandidateURL],
    registry_csv: Path = DEFAULT_REGISTRY_PATH,
    sources_yaml: Path = DEFAULT_SOURCES_YAML_PATH,
) -> CandidateSelection:
    known = load_known_urls(registry_csv, sources_yaml)
    seen_this_run: set[str] = set()
    new_candidates: list[CandidateURL] = []
    duplicate_candidates: list[CandidateURL] = []

    for candidate in candidates:
        normalized = normalize_url(candidate.url)
        if normalized in known or normalized in seen_this_run:
            duplicate_candidates.append(candidate)
            continue
        seen_this_run.add(normalized)
        new_candidates.append(candidate)

    return CandidateSelection(new_candidates, duplicate_candidates)


def download_candidates(
    candidates: list[CandidateURL],
    registry_csv: Path = DEFAULT_REGISTRY_PATH,
    sources_yaml: Path = DEFAULT_SOURCES_YAML_PATH,
    downloader: Any = download_sources,
) -> CandidateDownloadResult:
    selection = deduplicate_candidates(candidates, registry_csv, sources_yaml)
    downloaded: list[dict[str, Any]] = []
    failures: list[CandidateDownloadFailure] = []

    for candidate in selection.new_candidates:
        try:
            downloaded.extend(downloader(candidate.url, force=False))
        except Exception as exc:
            failures.append(CandidateDownloadFailure(candidate.url, str(exc)))

    return CandidateDownloadResult(
        downloaded=downloaded,
        duplicates=selection.duplicate_candidates,
        failures=failures,
    )


def run_monitor(
    paths: MonitoringPaths = MonitoringPaths(),
    registry_csv: Path = DEFAULT_REGISTRY_PATH,
    sources_yaml: Path = DEFAULT_SOURCES_YAML_PATH,
    report_dir: Path = DEFAULT_REPORT_DIR,
    client: Any | None = None,
    tavily_results: list[dict[str, Any]] | None = None,
    dry_run: bool = False,
    downloader: Any = download_sources,
) -> MonitoringRunResult:
    sources = load_monitoring_sources(paths)
    if sources.setup_gaps and not sources.endpoints:
        result = MonitoringRunResult(
            summary=_summary(
                dry_run=dry_run,
                setup_gaps=len(sources.setup_gaps),
            ),
            setup_gaps=sources.setup_gaps,
        )
        return _write_run_report(result, report_dir)

    candidates: list[CandidateURL] = []
    collection_failures: list[CollectionFailure] = []
    for endpoint in sources.endpoints:
        collection = collect_endpoint_candidates(endpoint, client)
        candidates.extend(collection.candidates)
        collection_failures.extend(collection.failures)

    tavily_rejections: list[CandidateRejection] = []
    tavily_accepted = 0
    if tavily_results:
        tavily = import_tavily_candidates(tavily_results, sources.endpoints)
        candidates.extend(tavily.candidates)
        tavily_rejections = tavily.rejections
        tavily_accepted = len(tavily.candidates)

    selection = deduplicate_candidates(candidates, registry_csv, sources_yaml)
    downloaded: list[dict[str, Any]] = []
    download_failures: list[CandidateDownloadFailure] = []
    if not dry_run:
        download = download_candidates(
            candidates,
            registry_csv=registry_csv,
            sources_yaml=sources_yaml,
            downloader=downloader,
        )
        downloaded = download.downloaded
        download_failures = download.failures
        duplicates = download.duplicates
    else:
        duplicates = selection.duplicate_candidates

    result = MonitoringRunResult(
        summary=_summary(
            dry_run=dry_run,
            setup_gaps=len(sources.setup_gaps),
            endpoints_checked=len(sources.endpoints),
            candidates_found=len(candidates),
            new_candidates=len(selection.new_candidates),
            duplicates_skipped=len(duplicates),
            collection_failures=len(collection_failures),
            tavily_accepted=tavily_accepted,
            tavily_rejected=len(tavily_rejections),
            downloads_completed=len(downloaded),
            download_failures=len(download_failures),
        ),
        candidates=selection.new_candidates,
        duplicates=duplicates,
        collection_failures=collection_failures,
        tavily_rejections=tavily_rejections,
        downloaded=downloaded,
        download_failures=download_failures,
    )
    return _write_run_report(result, report_dir)


def _summary(**overrides: int | bool) -> dict[str, int | bool]:
    summary: dict[str, int | bool] = {
        "dry_run": False,
        "setup_gaps": 0,
        "endpoints_checked": 0,
        "candidates_found": 0,
        "new_candidates": 0,
        "duplicates_skipped": 0,
        "collection_failures": 0,
        "tavily_accepted": 0,
        "tavily_rejected": 0,
        "downloads_completed": 0,
        "download_failures": 0,
    }
    summary.update(overrides)
    return summary


def _write_run_report(result: MonitoringRunResult, report_dir: Path) -> MonitoringRunResult:
    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report_path = report_dir / f"{timestamp}.json"
    report_path.write_text(
        json.dumps(_run_result_payload(result), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return MonitoringRunResult(
        summary=result.summary,
        setup_gaps=result.setup_gaps,
        candidates=result.candidates,
        duplicates=result.duplicates,
        collection_failures=result.collection_failures,
        tavily_rejections=result.tavily_rejections,
        downloaded=result.downloaded,
        download_failures=result.download_failures,
        report_path=report_path,
    )


def _run_result_payload(result: MonitoringRunResult) -> dict[str, Any]:
    return {
        "summary": result.summary,
        "setup_gaps": [_setup_gap_payload(gap) for gap in result.setup_gaps],
        "candidates": [_candidate_payload(candidate) for candidate in result.candidates],
        "duplicates": [_candidate_payload(candidate) for candidate in result.duplicates],
        "collection_failures": [failure.__dict__ for failure in result.collection_failures],
        "tavily_rejections": [rejection.__dict__ for rejection in result.tavily_rejections],
        "downloaded": result.downloaded,
        "download_failures": [failure.__dict__ for failure in result.download_failures],
    }


def _setup_gap_payload(gap: SetupGap) -> dict[str, str]:
    return {"path": str(gap.path), "message": gap.message}


def _candidate_payload(candidate: CandidateURL) -> dict[str, str]:
    return {
        "organization": candidate.organization,
        "endpoint_url": candidate.endpoint_url,
        "url": candidate.url,
        "title": candidate.title,
        "published_at": candidate.published_at,
        "source": candidate.source.value,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Monitor official red-flag source endpoints for new URLs.")
    parser.add_argument("--dry-run", action="store_true", help="Discover and report candidates without downloading.")
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument(
        "--tavily-results",
        type=Path,
        help="Optional JSON file containing Tavily MCP search results to validate and include as candidates.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    tavily_results = load_tavily_results_file(args.tavily_results) if args.tavily_results else None
    result = run_monitor(report_dir=args.report_dir, dry_run=args.dry_run, tavily_results=tavily_results)
    LOGGER.info(
        "Monitoring complete: checked=%s new=%s downloads=%s duplicates=%s failures=%s report=%s",
        result.summary["endpoints_checked"],
        result.summary["new_candidates"],
        result.summary["downloads_completed"],
        result.summary["duplicates_skipped"],
        result.summary["collection_failures"],
        result.report_path,
    )


if __name__ == "__main__":
    main()
