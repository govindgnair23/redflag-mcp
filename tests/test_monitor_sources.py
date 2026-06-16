"""Tests for scripts/monitor_sources.py."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from monitor_sources import (
    CandidateSource,
    CandidateURL,
    CollectionFailure,
    MonitoringEndpoint,
    MonitoringPaths,
    deduplicate_candidates,
    download_candidates,
    import_tavily_candidates,
    collect_endpoint_candidates,
    load_tavily_results_file,
    load_monitoring_sources,
    run_monitor,
)


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def make_catalogue(tmp_path: Path) -> MonitoringPaths:
    root = tmp_path / "source_file_catalogue"
    return MonitoringPaths(
        catalogue_dir=root,
        source_inventory=root / "source_inventory.csv",
        subscription_automation=root / "subscription_automation.csv",
        prioritization_ranking=root / "prioritization_ranking.csv",
        hidden_sources=root / "hidden_sources.csv",
    )


def write_valid_catalogue(paths: MonitoringPaths) -> None:
    write_csv(
        paths.source_inventory,
        [
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
        ],
        [
            {
                "Organization": "FinCEN",
                "Jurisdiction": "United States",
                "Link": "https://www.fincen.gov",
                "Publication Page": "https://www.fincen.gov/resources/advisoriesbulletinsfact-sheets",
                "Publication Types": "Advisory",
                "Update Frequency": "Ad hoc",
                "RSS Available (Yes/No)": "No",
                "Email Subscription Available (Yes/No)": "No",
                "API Available (Yes/No)": "No",
                "Historical Archive (Yes/No)": "Yes",
                "Relevant Categories": "AML; Fraud",
                "Monitoring Priority": "High",
            }
        ],
    )
    write_csv(
        paths.subscription_automation,
        [
            "Organization",
            "Feed Type (RSS/Email/API/XML/Open data)",
            "Exact Subscription URL",
            "Authentication Required (Yes/No)",
            "Update Frequency",
            "Notes",
        ],
        [
            {
                "Organization": "FinCEN",
                "Feed Type (RSS/Email/API/XML/Open data)": "HTML",
                "Exact Subscription URL": "Unspecified",
                "Authentication Required (Yes/No)": "No",
                "Update Frequency": "Ad hoc",
                "Notes": "Use publication page",
            }
        ],
    )
    write_csv(
        paths.prioritization_ranking,
        [
            "Rank",
            "Organization",
            "Jurisdiction",
            "Primary Risk Signals (list)",
            "Rationale",
            "Tier (1/2/3)",
        ],
        [
            {
                "Rank": "1",
                "Organization": "FinCEN",
                "Jurisdiction": "United States",
                "Primary Risk Signals (list)": "Fraud",
                "Rationale": "Best source",
                "Tier (1/2/3)": "1",
            }
        ],
    )
    write_csv(
        paths.hidden_sources,
        ["Organization/Consortium", "Jurisdiction", "Link", "Publication Types", "Relevance", "Notes"],
        [],
    )


def test_load_monitoring_sources_merges_inventory_subscription_and_priority(tmp_path):
    paths = make_catalogue(tmp_path)
    write_valid_catalogue(paths)

    result = load_monitoring_sources(paths)

    assert result.setup_gaps == []
    assert len(result.endpoints) == 1
    endpoint = result.endpoints[0]
    assert endpoint.organization == "FinCEN"
    assert endpoint.tier == 1
    assert endpoint.rank == 1
    assert endpoint.publication_page == "https://www.fincen.gov/resources/advisoriesbulletinsfact-sheets"
    assert endpoint.subscription_url == "Unspecified"
    assert endpoint.collection_method == "html"


def test_load_monitoring_sources_reports_empty_source_inventory(tmp_path):
    paths = make_catalogue(tmp_path)
    paths.catalogue_dir.mkdir(parents=True)
    paths.source_inventory.write_text("", encoding="utf-8")
    write_valid_catalogue(paths)
    paths.source_inventory.write_text("", encoding="utf-8")

    result = load_monitoring_sources(paths)

    assert any(gap.path == paths.source_inventory and "empty" in gap.message for gap in result.setup_gaps)
    assert result.endpoints == []


def test_load_monitoring_sources_reports_missing_subscription_headers(tmp_path):
    paths = make_catalogue(tmp_path)
    write_valid_catalogue(paths)
    write_csv(paths.subscription_automation, ["Organization", "Bad"], [{"Organization": "FinCEN", "Bad": "x"}])

    result = load_monitoring_sources(paths)

    assert any(
        gap.path == paths.subscription_automation and "missing required columns" in gap.message
        for gap in result.setup_gaps
    )


def test_load_monitoring_sources_reports_priority_without_matching_source(tmp_path):
    paths = make_catalogue(tmp_path)
    write_valid_catalogue(paths)
    write_csv(
        paths.prioritization_ranking,
        [
            "Rank",
            "Organization",
            "Jurisdiction",
            "Primary Risk Signals (list)",
            "Rationale",
            "Tier (1/2/3)",
        ],
        [
            {
                "Rank": "2",
                "Organization": "Unknown FIU",
                "Jurisdiction": "Nowhere",
                "Primary Risk Signals (list)": "Fraud",
                "Rationale": "Missing",
                "Tier (1/2/3)": "1",
            }
        ],
    )

    result = load_monitoring_sources(paths)

    assert any("Unknown FIU" in gap.message for gap in result.setup_gaps)


class FakeResponse:
    def __init__(
        self,
        text: str = "",
        json_data: object | None = None,
        status_error: Exception | None = None,
        final_url: str | None = None,
    ) -> None:
        self.text = text
        self._json_data = json_data
        self._status_error = status_error
        self.url = final_url or "https://example.gov/feed"

    def raise_for_status(self) -> None:
        if self._status_error:
            raise self._status_error

    def json(self) -> object:
        if self._json_data is None:
            raise ValueError("not json")
        return self._json_data


class FakeClient:
    def __init__(self, response: FakeResponse | Exception) -> None:
        self.response = response
        self.requests: list[str] = []

    def get(self, url: str, **kwargs) -> FakeResponse:
        self.requests.append(url)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def endpoint(**overrides: object) -> MonitoringEndpoint:
    values = {
        "organization": "FinCEN",
        "jurisdiction": "United States",
        "publication_page": "https://www.fincen.gov/resources/advisoriesbulletinsfact-sheets",
        "publication_types": "Advisory",
        "relevant_categories": "AML; Fraud",
        "monitoring_priority": "High",
        "feed_type": "RSS",
        "subscription_url": "https://www.fincen.gov/feed.xml",
        "rank": 1,
        "tier": 1,
    }
    values.update(overrides)
    return MonitoringEndpoint(**values)


def test_collect_endpoint_candidates_reads_rss_items():
    feed = """<?xml version="1.0"?>
    <rss><channel>
      <item>
        <title>FinCEN Advisory on Fraud</title>
        <link>https://www.fincen.gov/news/advisory-fraud</link>
        <pubDate>Mon, 01 Jun 2026 00:00:00 GMT</pubDate>
      </item>
      <item>
        <title>FinCEN Alert PDF</title>
        <link>https://www.fincen.gov/system/files/alert.pdf</link>
      </item>
    </channel></rss>
    """

    result = collect_endpoint_candidates(endpoint(), FakeClient(FakeResponse(text=feed)))

    assert result.failures == []
    assert [candidate.url for candidate in result.candidates] == [
        "https://www.fincen.gov/news/advisory-fraud",
        "https://www.fincen.gov/system/files/alert.pdf",
    ]
    assert result.candidates[0].title == "FinCEN Advisory on Fraud"
    assert result.candidates[0].published_at == "Mon, 01 Jun 2026 00:00:00 GMT"
    assert result.candidates[0].source == CandidateSource.ENDPOINT


def test_collect_endpoint_candidates_reads_json_links():
    response = FakeResponse(
        json_data={
            "items": [
                {"title": "CISA KEV", "url": "https://www.cisa.gov/known-exploited-vulnerabilities-catalog"},
                {"download_url": "https://www.cisa.gov/sites/default/files/known_exploited_vulnerabilities.json"},
            ]
        }
    )

    result = collect_endpoint_candidates(
        endpoint(
            organization="CISA",
            feed_type="API",
            subscription_url="https://www.cisa.gov/known-exploited-vulnerabilities-catalog.json",
        ),
        FakeClient(response),
    )

    assert result.failures == []
    assert {candidate.url for candidate in result.candidates} == {
        "https://www.cisa.gov/known-exploited-vulnerabilities-catalog",
        "https://www.cisa.gov/sites/default/files/known_exploited_vulnerabilities.json",
    }


def test_collect_endpoint_candidates_bounds_html_to_official_domain():
    html = """
    <html><body>
      <a href="/system/files/advisory.pdf">Official PDF</a>
      <a href="https://www.fincen.gov/news/advisory">Official Page</a>
      <a href="https://vendor.example/blog">Vendor Blog</a>
    </body></html>
    """

    result = collect_endpoint_candidates(
        endpoint(feed_type="HTML", subscription_url="Unspecified"),
        FakeClient(FakeResponse(text=html, final_url="https://www.fincen.gov/resources/advisoriesbulletinsfact-sheets")),
    )

    assert result.failures == []
    assert {candidate.url for candidate in result.candidates} == {
        "https://www.fincen.gov/system/files/advisory.pdf",
        "https://www.fincen.gov/news/advisory",
    }


def test_collect_endpoint_candidates_records_endpoint_failure():
    result = collect_endpoint_candidates(endpoint(), FakeClient(RuntimeError("timeout")))

    assert result.candidates == []
    assert result.failures == [
        CollectionFailure(
            organization="FinCEN",
            endpoint_url="https://www.fincen.gov/feed.xml",
            message="timeout",
        )
    ]


def test_import_tavily_candidates_accepts_known_regulator_domain():
    result = import_tavily_candidates(
        [
            {
                "url": "https://www.fincen.gov/news/news-releases/fincen-alert",
                "title": "FinCEN alert",
            }
        ],
        [],
    )

    assert result.rejections == []
    assert len(result.candidates) == 1
    assert result.candidates[0].source == CandidateSource.TAVILY
    assert result.candidates[0].organization == "FinCEN"


def test_import_tavily_candidates_accepts_source_inventory_domain():
    result = import_tavily_candidates(
        [{"url": "https://custom-fiu.example.gov/advisories/new", "title": "Custom FIU"}],
        [
            endpoint(
                organization="Custom FIU",
                publication_page="https://custom-fiu.example.gov/advisories",
                subscription_url="Unspecified",
            )
        ],
    )

    assert result.rejections == []
    assert result.candidates[0].organization == "Custom FIU"


def test_import_tavily_candidates_rejects_non_official_domain():
    result = import_tavily_candidates(
        [{"url": "https://vendor.example/blog/fincen-alert", "title": "Vendor post"}],
        [],
    )

    assert result.candidates == []
    assert result.rejections[0].url == "https://vendor.example/blog/fincen-alert"
    assert "not an official regulator domain" in result.rejections[0].reason


def test_import_tavily_candidates_rejects_malformed_result():
    result = import_tavily_candidates([{"title": "No URL"}], [])

    assert result.candidates == []
    assert result.rejections[0].url == ""
    assert "missing URL" in result.rejections[0].reason


def test_load_tavily_results_file_accepts_list_or_results_key(tmp_path):
    list_file = tmp_path / "list.json"
    list_file.write_text('[{"url": "https://www.fincen.gov/a"}]', encoding="utf-8")
    keyed_file = tmp_path / "keyed.json"
    keyed_file.write_text('{"results": [{"url": "https://www.fincen.gov/b"}]}', encoding="utf-8")

    assert load_tavily_results_file(list_file) == [{"url": "https://www.fincen.gov/a"}]
    assert load_tavily_results_file(keyed_file) == [{"url": "https://www.fincen.gov/b"}]


def test_deduplicate_candidates_checks_registry_and_sources_yaml(tmp_path):
    registry_csv = tmp_path / "registry.csv"
    write_csv(
        registry_csv,
        ["status", "source_url"],
        [{"status": "downloaded", "source_url": "https://example.gov/known"}],
    )
    sources_yaml = tmp_path / "sources.yaml"
    sources_yaml.write_text("'001':\n  url: https://example.gov/source-only\n", encoding="utf-8")
    candidates = [
        CandidateURL("FinCEN", "feed", "https://example.gov/new", "New"),
        CandidateURL("FinCEN", "feed", "https://example.gov/known/", "Known"),
        CandidateURL("FinCEN", "feed", "https://example.gov/source-only", "Source Only"),
        CandidateURL("FinCEN", "feed", "https://example.gov/new/", "Duplicate New"),
    ]

    selection = deduplicate_candidates(candidates, registry_csv, sources_yaml)

    assert [candidate.url for candidate in selection.new_candidates] == ["https://example.gov/new"]
    assert [candidate.url for candidate in selection.duplicate_candidates] == [
        "https://example.gov/known/",
        "https://example.gov/source-only",
        "https://example.gov/new/",
    ]


def test_download_candidates_calls_pipeline_for_new_urls_only(tmp_path):
    registry_csv = tmp_path / "registry.csv"
    write_csv(registry_csv, ["status", "source_url"], [{"status": "downloaded", "source_url": "https://example.gov/known"}])
    sources_yaml = tmp_path / "sources.yaml"
    sources_yaml.write_text("{}\n", encoding="utf-8")
    called: list[str] = []

    def fake_downloader(url: str, force: bool = False):
        called.append(url)
        return [{"url": url, "kind": "pdf"}]

    result = download_candidates(
        [
            CandidateURL("FinCEN", "feed", "https://example.gov/new", "New"),
            CandidateURL("FinCEN", "feed", "https://example.gov/known", "Known"),
        ],
        registry_csv,
        sources_yaml,
        downloader=fake_downloader,
    )

    assert called == ["https://example.gov/new"]
    assert result.downloaded == [{"url": "https://example.gov/new", "kind": "pdf"}]
    assert [candidate.url for candidate in result.duplicates] == ["https://example.gov/known"]
    assert result.failures == []


def test_download_candidates_records_download_failures(tmp_path):
    registry_csv = tmp_path / "registry.csv"
    write_csv(registry_csv, ["status", "source_url"], [])
    sources_yaml = tmp_path / "sources.yaml"
    sources_yaml.write_text("{}\n", encoding="utf-8")

    def fake_downloader(url: str, force: bool = False):
        raise RuntimeError("download failed")

    result = download_candidates(
        [CandidateURL("FinCEN", "feed", "https://example.gov/fail", "Fail")],
        registry_csv,
        sources_yaml,
        downloader=fake_downloader,
    )

    assert result.downloaded == []
    assert result.failures[0].url == "https://example.gov/fail"
    assert "download failed" in result.failures[0].reason


def test_run_monitor_dry_run_writes_report_without_downloading(tmp_path):
    paths = make_catalogue(tmp_path)
    write_valid_catalogue(paths)
    write_csv(
        paths.subscription_automation,
        [
            "Organization",
            "Feed Type (RSS/Email/API/XML/Open data)",
            "Exact Subscription URL",
            "Authentication Required (Yes/No)",
            "Update Frequency",
            "Notes",
        ],
        [
            {
                "Organization": "FinCEN",
                "Feed Type (RSS/Email/API/XML/Open data)": "RSS",
                "Exact Subscription URL": "https://www.fincen.gov/feed.xml",
                "Authentication Required (Yes/No)": "No",
                "Update Frequency": "Ad hoc",
                "Notes": "Test feed",
            }
        ],
    )
    report_dir = tmp_path / "monitoring_runs"
    feed = """<rss><channel><item><title>New Alert</title><link>https://www.fincen.gov/new-alert</link></item></channel></rss>"""
    called: list[str] = []

    result = run_monitor(
        paths=paths,
        registry_csv=tmp_path / "registry.csv",
        sources_yaml=tmp_path / "sources.yaml",
        report_dir=report_dir,
        client=FakeClient(FakeResponse(text=feed)),
        dry_run=True,
        downloader=lambda url, force=False: called.append(url),
    )

    assert called == []
    assert result.summary["endpoints_checked"] == 1
    assert result.summary["new_candidates"] == 1
    assert result.summary["downloads_completed"] == 0
    reports = sorted(report_dir.glob("*.json"))
    assert len(reports) == 1
    report = json.loads(reports[0].read_text(encoding="utf-8"))
    assert report["summary"]["dry_run"] is True
    assert report["candidates"][0]["url"] == "https://www.fincen.gov/new-alert"


def test_run_monitor_includes_tavily_counts_and_downloads(tmp_path):
    paths = make_catalogue(tmp_path)
    write_valid_catalogue(paths)
    registry_csv = tmp_path / "registry.csv"
    write_csv(registry_csv, ["status", "source_url"], [])
    sources_yaml = tmp_path / "sources.yaml"
    sources_yaml.write_text("{}\n", encoding="utf-8")

    result = run_monitor(
        paths=paths,
        registry_csv=registry_csv,
        sources_yaml=sources_yaml,
        report_dir=tmp_path / "reports",
        client=FakeClient(FakeResponse(text="<rss><channel /></rss>")),
        tavily_results=[
            {"url": "https://www.fincen.gov/tavily-alert", "title": "Official"},
            {"url": "https://vendor.example/tavily-alert", "title": "Vendor"},
        ],
        downloader=lambda url, force=False: [{"url": url, "kind": "web"}],
    )

    assert result.summary["tavily_accepted"] == 1
    assert result.summary["tavily_rejected"] == 1
    assert result.summary["downloads_completed"] == 1
    assert result.downloaded == [{"url": "https://www.fincen.gov/tavily-alert", "kind": "web"}]


def test_run_monitor_reports_setup_gaps_without_collecting(tmp_path):
    paths = make_catalogue(tmp_path)
    paths.catalogue_dir.mkdir(parents=True)
    paths.source_inventory.write_text("", encoding="utf-8")

    result = run_monitor(paths=paths, report_dir=tmp_path / "reports", client=FakeClient(RuntimeError("should not run")))

    assert result.summary["setup_gaps"] >= 1
    assert result.summary["endpoints_checked"] == 0
    assert result.candidates == []
