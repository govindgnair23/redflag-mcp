"""Tests for scripts/review_markdown_sources.py."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from review_markdown_sources import (
    CSV_HEADER,
    MarkdownMetadata,
    build_catalog_row,
    classify_markdown,
    load_catalog_by_url,
    parse_markdown_metadata,
    review_markdown_sources,
)


def test_parse_markdown_metadata_extracts_header_fields():
    text = """Title: Example Red Flags

URL Source: https://example.gov/red-flags

Published Time: 2025-07-21T17:04:07+01:00

Warning: Target URL returned error 404: Not Found

Markdown Content:
# Example
"""

    assert parse_markdown_metadata(text) == MarkdownMetadata(
        title="Example Red Flags",
        url="https://example.gov/red-flags",
        published_time="2025-07-21T17:04:07+01:00",
        warning="Target URL returned error 404: Not Found",
    )


def test_classify_markdown_keeps_red_flag_content():
    text = """Title: Indicators
URL Source: https://example.gov/indicators
Markdown Content:
# Money laundering and terrorist financing indicators
The following red flags and suspicious activity indicators may indicate money laundering.
* Customer uses unusual identification documents.
"""

    decision = classify_markdown(text)

    assert decision.keep is True
    assert "red-flag terms" in decision.reason


def test_classify_markdown_keeps_relevant_report_landing_page():
    text = """Title: Sanctions compliance in the Cryptoassets sector: Threat Assessment
URL Source: https://www.gov.uk/government/publications/sanctions-compliance-in-the-cryptoassets-sector-threat-assessment
Markdown Content:
# Sanctions compliance in the Cryptoassets sector: Threat Assessment
Assessment of threats to UK financial sanctions compliance.
### [Sanctions compliance in the Cryptoassets sector: Threat Assessment](https://assets.example.gov/OFSI_Cryptoassets_Threat_Assessment.pdf)
This publication is one in a series of sector-specific assessments addressing threats to UK financial sanctions compliance.
"""

    decision = classify_markdown(text)

    assert decision.keep is True


def test_classify_markdown_archives_404_captcha_and_generic_index_pages():
    assert classify_markdown(
        "Title: 404\nWarning: Target URL returned error 404: Not Found\nMarkdown Content:\n"
    ).keep is False
    assert classify_markdown(
        "Title: Just a moment...\nWarning: This page maybe requiring CAPTCHA\nMarkdown Content:\n"
    ).keep is False
    assert classify_markdown(
        """Title: Homepage
URL Source: https://example.gov
Markdown Content:
* Home
* About us
* Contact
* Privacy policy
"""
    ).keep is False


def test_build_catalog_row_reuses_existing_catalog_metadata(tmp_path):
    catalog = tmp_path / "catalog.csv"
    with catalog.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADER)
        writer.writeheader()
        writer.writerow(
            {
                "Region": "North America",
                "Country/Jurisdiction": "Canada",
                "Issuing Body": "FINTRAC",
                "Document Title": "Existing Indicators",
                "Document Type": "Indicator list",
                "Year/Date Published": "Updated",
                "Primary Topic / Predicate Crime / Typology Area": "All ML/TF",
                "Brief Summary": "Existing summary",
                "Direct URL": "https://example.gov/indicators",
                "Target Audience / Reporting Entity Sector": "Financial entities",
            }
        )
    existing = load_catalog_by_url(catalog)
    metadata = MarkdownMetadata(
        title="Different Captured Title",
        url="https://example.gov/indicators",
        published_time="2026-01-01",
        warning="",
    )

    row = build_catalog_row(metadata, "irrelevant text", existing)

    assert row["Document Title"] == "Existing Indicators"
    assert row["Issuing Body"] == "FINTRAC"
    assert row["Direct URL"] == "https://example.gov/indicators"


def test_review_writes_valid_csv_and_archives_invalid_files(tmp_path):
    markdown_dir = tmp_path / "markdown"
    archive_dir = markdown_dir / "archive"
    markdown_dir.mkdir()
    valid = markdown_dir / "001.md"
    invalid = markdown_dir / "002.md"
    valid.write_text(
        """Title: AUSTRAC suspicious activity indicators
URL Source: https://www.austrac.gov.au/example
Published Time: 2024-01-02
Markdown Content:
# Indicators of suspicious activity for the banking sector
These red flags may indicate money laundering or terrorism financing.
""",
        encoding="utf-8",
    )
    invalid.write_text(
        "Title: Page not found\nWarning: Target URL returned error 404: Not Found\n",
        encoding="utf-8",
    )
    catalog = tmp_path / "catalog.csv"
    with catalog.open("w", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=CSV_HEADER).writeheader()
    output_csv = tmp_path / "out.csv"

    result = review_markdown_sources(
        markdown_dir=markdown_dir,
        catalog_csv=catalog,
        output_csv=output_csv,
        archive_dir=archive_dir,
    )

    assert result.kept == 1
    assert result.archived == 1
    assert valid.exists()
    assert not invalid.exists()
    assert (archive_dir / "002.md").exists()

    with output_csv.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["Document Title"] == "AUSTRAC suspicious activity indicators"
    assert rows[0]["Direct URL"] == "https://www.austrac.gov.au/example"
    assert rows[0]["Issuing Body"] == "AUSTRAC"
