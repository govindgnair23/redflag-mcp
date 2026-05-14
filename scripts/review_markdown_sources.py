#!/usr/bin/env python3
"""Review harvested markdown sources and catalog usable red-flag documents."""

from __future__ import annotations

import argparse
import csv
import logging
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MARKDOWN_DIR = PROJECT_ROOT / "red_flag_sources" / "markdown"
DEFAULT_ARCHIVE_DIR = DEFAULT_MARKDOWN_DIR / "archive"
DEFAULT_CATALOG_CSV = (
    PROJECT_ROOT / "red_flag_sources" / "Global_AML_CFT_Sanctions_Red_Flag_Catalog.csv"
)
DEFAULT_OUTPUT_CSV = PROJECT_ROOT / "red_flag_sources" / "Markdown_Red_Flag_Source_Catalog.csv"

CSV_HEADER = [
    "Region",
    "Country/Jurisdiction",
    "Issuing Body",
    "Document Title",
    "Document Type",
    "Year/Date Published",
    "Primary Topic / Predicate Crime / Typology Area",
    "Brief Summary",
    "Direct URL",
    "Target Audience / Reporting Entity Sector",
]

BAD_CAPTURE_PATTERNS = [
    "target url returned error 404",
    "page maybe requiring captcha",
    "just a moment",
    "access denied",
    "not yet fully loaded",
]

BAD_TITLE_PATTERNS = [
    "404",
    "page not found",
    "not found",
    "resource not found",
    "we couldn't find that web page",
    "just a moment",
]

RED_FLAG_PATTERNS = [
    (r"\bred flags?\b", 4),
    (r"\bindicators?\b", 3),
    (r"\btypolog(?:y|ies)\b", 3),
    (r"\bsuspicious activit(?:y|ies)\b", 3),
    (r"\bsuspicious transaction", 3),
    (r"\bmoney laundering\b", 2),
    (r"\bterroris[mt] financing\b", 2),
    (r"\baml/cft\b", 2),
    (r"\bsanctions? (?:evasion|compliance|circumvention|risk)", 2),
    (r"\bproliferation financing\b", 2),
    (r"\bthreat assessment\b", 2),
    (r"\brisk assessment\b", 2),
    (r"\bpredicate crime\b", 2),
    (r"\bfinancial crime\b", 1),
]

DOMAIN_DEFAULTS = {
    "bsaaml.ffiec.gov": ("North America", "United States", "FFIEC"),
    "fintrac-canafe.canada.ca": ("North America", "Canada", "FINTRAC"),
    "www.finra.org": ("North America", "United States", "FINRA"),
    "ofac.treasury.gov": ("North America", "United States", "OFAC"),
    "www.gov.uk": ("Europe", "United Kingdom", "OFSI/HM Government"),
    "www.eba.europa.eu": ("Europe", "European Union", "EBA"),
    "www.europol.europa.eu": ("Europe", "European Union", "Europol"),
    "uif.bancaditalia.it": ("Europe", "Italy", "UIF"),
    "www.mas.gov.sg": ("Asia-Pacific", "Singapore", "MAS"),
    "www.jfiu.gov.hk": ("Asia-Pacific", "Hong Kong", "JFIU"),
    "rulebook.centralbank.ae": ("Middle East", "United Arab Emirates", "CBUAE"),
    "www.austrac.gov.au": ("Asia-Pacific", "Australia", "AUSTRAC"),
    "www.fatf-gafi.org": ("International", "International", "FATF"),
    "wolfsberg-group.org": ("International", "International", "Wolfsberg Group"),
    "www.bis.org": ("International", "International", "BIS/BCBS"),
}

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class MarkdownMetadata:
    title: str
    url: str
    published_time: str
    warning: str


@dataclass(frozen=True)
class Classification:
    keep: bool
    reason: str


@dataclass(frozen=True)
class ReviewResult:
    kept: int
    archived: int
    skipped_duplicates: int
    output_csv: Path
    archive_dir: Path


def parse_markdown_metadata(text: str) -> MarkdownMetadata:
    fields = {
        "title": "",
        "url": "",
        "published_time": "",
        "warning": "",
    }
    for line in text.splitlines()[:40]:
        if line.startswith("Title:"):
            fields["title"] = line.removeprefix("Title:").strip()
        elif line.startswith("URL Source:"):
            fields["url"] = line.removeprefix("URL Source:").strip()
        elif line.startswith("Published Time:"):
            fields["published_time"] = line.removeprefix("Published Time:").strip()
        elif line.startswith("Warning:"):
            fields["warning"] = line.removeprefix("Warning:").strip()
    return MarkdownMetadata(**fields)


def classify_markdown(text: str) -> Classification:
    metadata = parse_markdown_metadata(text)
    normalized_title = metadata.title.casefold()
    normalized_warning = metadata.warning.casefold()
    normalized_text = text.casefold()

    if any(pattern in normalized_warning for pattern in BAD_CAPTURE_PATTERNS):
        return Classification(False, f"bad capture warning: {metadata.warning}")
    if any(pattern == normalized_title or pattern in normalized_title for pattern in BAD_TITLE_PATTERNS):
        return Classification(False, f"bad capture title: {metadata.title}")

    score = 0
    matched_terms: list[str] = []
    for pattern, weight in RED_FLAG_PATTERNS:
        if re.search(pattern, normalized_text):
            score += weight
            matched_terms.append(pattern)

    if score >= 3:
        return Classification(True, f"matched red-flag terms: {', '.join(matched_terms[:3])}")

    content = _content_after_marker(text)
    content_words = re.findall(r"[a-zA-Z]{3,}", content)
    if len(content_words) < 25:
        return Classification(False, "too little captured content")

    if _looks_like_navigation_only(content):
        return Classification(False, "navigation or index page without usable source content")

    return Classification(False, "no usable red-flag source content detected")


def load_catalog_by_url(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return {
            row.get("Direct URL", "").strip(): {key: row.get(key, "") for key in CSV_HEADER}
            for row in reader
            if row.get("Direct URL", "").strip()
        }


def build_catalog_row(
    metadata: MarkdownMetadata,
    text: str,
    existing_catalog: dict[str, dict[str, str]],
) -> dict[str, str]:
    if metadata.url in existing_catalog:
        return dict(existing_catalog[metadata.url])

    region, country, issuer = _infer_source_identity(metadata.url)
    return {
        "Region": region,
        "Country/Jurisdiction": country,
        "Issuing Body": issuer,
        "Document Title": metadata.title,
        "Document Type": _infer_document_type(metadata.title, text),
        "Year/Date Published": _infer_year(metadata.published_time, text),
        "Primary Topic / Predicate Crime / Typology Area": _infer_topic(metadata.title, text),
        "Brief Summary": _infer_summary(metadata.title, text),
        "Direct URL": metadata.url,
        "Target Audience / Reporting Entity Sector": _infer_audience(text),
    }


def review_markdown_sources(
    markdown_dir: Path = DEFAULT_MARKDOWN_DIR,
    catalog_csv: Path = DEFAULT_CATALOG_CSV,
    output_csv: Path = DEFAULT_OUTPUT_CSV,
    archive_dir: Path = DEFAULT_ARCHIVE_DIR,
) -> ReviewResult:
    existing_catalog = load_catalog_by_url(catalog_csv)
    archive_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    kept = 0
    archived = 0
    skipped_duplicates = 0

    for path in sorted(markdown_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        metadata = parse_markdown_metadata(text)
        decision = classify_markdown(text)

        if decision.keep and metadata.url:
            if metadata.url in seen_urls:
                skipped_duplicates += 1
                LOGGER.info("Duplicate URL skipped: %s", path.name)
                continue
            rows.append(build_catalog_row(metadata, text, existing_catalog))
            seen_urls.add(metadata.url)
            kept += 1
            LOGGER.info("Kept %s: %s", path.name, decision.reason)
            continue

        target = archive_dir / path.name
        if target.exists():
            target.unlink()
        shutil.move(str(path), str(target))
        archived += 1
        LOGGER.info("Archived %s: %s", path.name, decision.reason)

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADER)
        writer.writeheader()
        writer.writerows(rows)

    return ReviewResult(
        kept=kept,
        archived=archived,
        skipped_duplicates=skipped_duplicates,
        output_csv=output_csv,
        archive_dir=archive_dir,
    )


def _content_after_marker(text: str) -> str:
    marker = "Markdown Content:"
    if marker not in text:
        return text
    return text.split(marker, 1)[1]


def _looks_like_navigation_only(content: str) -> bool:
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    if not lines:
        return True
    nav_lines = sum(
        1
        for line in lines
        if line.startswith(("*", "-", "[", "!["))
        or line.casefold() in {"home", "contact us", "privacy policy", "terms & conditions"}
    )
    return nav_lines / len(lines) > 0.75


def _infer_source_identity(url: str) -> tuple[str, str, str]:
    host = urlparse(url).netloc.casefold()
    host = host.removeprefix("r.jina.ai/http://").removeprefix("r.jina.ai/https://")
    if host in DOMAIN_DEFAULTS:
        return DOMAIN_DEFAULTS[host]
    return "", "", ""


def _infer_document_type(title: str, text: str) -> str:
    haystack = f"{title}\n{text[:2000]}".casefold()
    type_patterns = [
        ("red alert", "Red Alert"),
        ("operational alert", "Operational Alert"),
        ("alert", "Alert"),
        ("advisory", "Advisory"),
        ("guidance", "Guidance"),
        ("guidelines", "Guidelines"),
        ("indicator", "Indicator list"),
        ("typolog", "Typology"),
        ("risk assessment", "Risk Assessment"),
        ("threat assessment", "Threat Assessment"),
        ("manual", "Manual"),
        ("notice", "Notice"),
        ("report", "Report"),
    ]
    for needle, label in type_patterns:
        if needle in haystack:
            return label
    return ""


def _infer_year(published_time: str, text: str) -> str:
    if published_time:
        year_match = re.search(r"\b(19|20)\d{2}\b", published_time)
        if year_match:
            return year_match.group(0)
    year_match = re.search(r"\b(20[0-3]\d|19\d{2})\b", text[:3000])
    return year_match.group(0) if year_match else ""


def _infer_topic(title: str, text: str) -> str:
    haystack = f"{title}\n{text[:5000]}".casefold()
    topics = [
        ("trade-based money laundering", "Trade-based money laundering"),
        ("virtual currency", "Virtual assets / crypto"),
        ("cryptoasset", "Virtual assets / crypto"),
        ("crypto", "Virtual assets / crypto"),
        ("sanctions", "Sanctions / sanctions evasion"),
        ("proliferation financing", "Proliferation financing"),
        ("terrorist financing", "Terrorist financing"),
        ("human trafficking", "Human trafficking"),
        ("child sexual exploitation", "Online child sexual exploitation"),
        ("real estate", "Real estate"),
        ("money services business", "Money services businesses"),
        ("securities", "Securities"),
        ("banking", "Banking"),
        ("fraud", "Fraud"),
        ("money laundering", "Money laundering"),
    ]
    for needle, label in topics:
        if needle in haystack:
            return label
    return ""


def _infer_summary(title: str, text: str) -> str:
    content = re.sub(r"\s+", " ", _content_after_marker(text)).strip()
    if not content:
        return ""
    first_sentence = re.split(r"(?<=[.!?])\s+", content, maxsplit=1)[0]
    if len(first_sentence) > 240:
        first_sentence = first_sentence[:237].rstrip() + "..."
    if first_sentence.startswith("#"):
        first_sentence = first_sentence.lstrip("# ").strip()
    if first_sentence and first_sentence != title:
        return first_sentence
    return f"Captured source page for {title}." if title else ""


def _infer_audience(text: str) -> str:
    haystack = text.casefold()
    audiences = []
    for needle, label in [
        ("financial institution", "Financial institutions"),
        ("bank", "Banks"),
        ("money services business", "MSBs"),
        ("virtual asset", "VASPs"),
        ("cryptoasset", "Cryptoasset firms"),
        ("securities", "Securities firms"),
        ("real estate", "Real estate sector"),
        ("dnfbp", "DNFBPs"),
        ("reporting entit", "Reporting entities"),
    ]:
        if needle in haystack:
            audiences.append(label)
    return ", ".join(dict.fromkeys(audiences))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Review harvested markdown files and write a catalog of usable red-flag sources."
    )
    parser.add_argument("--markdown-dir", type=Path, default=DEFAULT_MARKDOWN_DIR)
    parser.add_argument("--catalog-csv", type=Path, default=DEFAULT_CATALOG_CSV)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--archive-dir", type=Path, default=DEFAULT_ARCHIVE_DIR)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    result = review_markdown_sources(
        markdown_dir=args.markdown_dir,
        catalog_csv=args.catalog_csv,
        output_csv=args.output_csv,
        archive_dir=args.archive_dir,
    )
    LOGGER.info(
        "Review complete: %d kept, %d archived, %d duplicate URLs skipped -> %s",
        result.kept,
        result.archived,
        result.skipped_duplicates,
        result.output_csv,
    )


if __name__ == "__main__":
    main()
