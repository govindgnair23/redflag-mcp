"""Tests for scripts/build_registry.py."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from build_registry import (
    REGISTRY_COLUMNS,
    build_catalog_rows,
    build_extracted_rows,
    build_registry,
    load_catalogs,
    load_extraction_manifest,
    load_sources_yaml,
)


CATALOG_HEADER = [
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


def write_catalog(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CATALOG_HEADER)
        writer.writeheader()
        writer.writerows(rows)


def test_load_catalogs_normalizes_urls_and_handles_missing_files(tmp_path):
    catalog = tmp_path / "catalog.csv"
    write_catalog(
        catalog,
        [
            {
                "Region": "North America",
                "Country/Jurisdiction": "United States",
                "Issuing Body": "FinCEN",
                "Document Title": "First Source",
                "Document Type": "Advisory",
                "Year/Date Published": "2024",
                "Primary Topic / Predicate Crime / Typology Area": "Fraud",
                "Brief Summary": "Summary",
                "Direct URL": " https://example.gov/source/ ",
                "Target Audience / Reporting Entity Sector": "Banks",
            },
            {
                "Region": "Europe",
                "Country/Jurisdiction": "United Kingdom",
                "Issuing Body": "OFSI",
                "Document Title": "Second Source",
                "Document Type": "Guidance",
                "Year/Date Published": "2025",
                "Primary Topic / Predicate Crime / Typology Area": "Sanctions",
                "Brief Summary": "Summary",
                "Direct URL": "https://example.gov/other",
                "Target Audience / Reporting Entity Sector": "Firms",
            },
        ],
    )

    rows = load_catalogs([catalog, tmp_path / "missing.csv"])

    assert [row["Direct URL"] for row in rows] == [
        "https://example.gov/source",
        "https://example.gov/other",
    ]


def test_load_sources_yaml_returns_serial_key_url_mapping(tmp_path):
    sources = tmp_path / "sources.yaml"
    sources.write_text(
        yaml.safe_dump(
            {
                "001": {"url": "https://example.gov/one"},
                "207": {"url": "https://example.gov/two/"},
            }
        ),
        encoding="utf-8",
    )

    assert load_sources_yaml(sources) == {
        "001": "https://example.gov/one",
        "207": "https://example.gov/two",
    }
    assert load_sources_yaml(tmp_path / "missing.yaml") == {}


def test_load_extraction_manifest_keys_extracted_at_by_output_file(tmp_path):
    manifest = tmp_path / ".extracted_sources.yaml"
    manifest.write_text(
        yaml.safe_dump(
            [
                {
                    "source": "/tmp/207.pdf",
                    "slug": "example",
                    "output_file": "data/source/207.yaml",
                    "extracted_at": "2026-05-17T12:00:00Z",
                },
                {
                    "source": "/tmp/208.pdf",
                    "slug": "other",
                    "output_file": "data/source/208.yaml",
                    "extracted_at": "2026-05-17T13:00:00Z",
                },
            ]
        ),
        encoding="utf-8",
    )

    assert load_extraction_manifest(manifest) == {
        "data/source/207.yaml": "2026-05-17T12:00:00Z",
        "data/source/208.yaml": "2026-05-17T13:00:00Z",
    }
    assert load_extraction_manifest(tmp_path / "missing.yaml") == {}


def test_build_extracted_rows_derives_metadata_and_primary_category(tmp_path):
    yaml_dir = tmp_path / "source"
    yaml_dir.mkdir()
    (yaml_dir / "207.yaml").write_text(
        yaml.safe_dump(
            [
                {
                    "regulatory_source": "Example Indicators",
                    "regulator": "FINTRAC",
                    "regulator_jurisdiction": "Canada",
                    "issued_date": "2024-01-01",
                    "source_url": "https://example.gov/indicators/",
                    "category": "sanctions_evasion",
                },
                {"category": "layering"},
                {"category": "sanctions_evasion"},
                {"category": "layering"},
                {"category": "sanctions_evasion"},
            ]
        ),
        encoding="utf-8",
    )
    (yaml_dir / ".extracted_sources.yaml").write_text("[]\n", encoding="utf-8")

    rows = build_extracted_rows(
        yaml_dir,
        {"data/source/207.yaml": "2026-05-17T12:00:00Z"},
    )

    assert rows == [
        {
            "status": "extracted",
            "slug": "207",
            "document_title": "Example Indicators",
            "regulator": "FINTRAC",
            "jurisdiction": "Canada",
            "issued_date": "2024-01-01",
            "source_url": "https://example.gov/indicators",
            "primary_category": "sanctions_evasion",
            "red_flag_count": "5",
            "output_file": "data/source/207.yaml",
            "extracted_at": "2026-05-17T12:00:00Z",
        }
    ]


def test_build_extracted_rows_uses_single_category_and_empty_missing_manifest(tmp_path):
    yaml_dir = tmp_path / "source"
    yaml_dir.mkdir()
    (yaml_dir / "208.yaml").write_text(
        yaml.safe_dump(
            [
                {
                    "regulatory_source": "Single Flag",
                    "regulator": "FinCEN",
                    "regulator_jurisdiction": "United States",
                    "issued_date": "2025",
                    "source_url": "https://example.gov/single",
                    "category": "fraud",
                }
            ]
        ),
        encoding="utf-8",
    )

    rows = build_extracted_rows(yaml_dir, {})

    assert rows[0]["primary_category"] == "fraud"
    assert rows[0]["red_flag_count"] == "1"
    assert rows[0]["extracted_at"] == ""


def test_build_catalog_rows_derives_downloaded_and_not_downloaded_statuses():
    catalogs = [
        {
            "Country/Jurisdiction": "United States",
            "Issuing Body": "FinCEN",
            "Document Title": "Already Extracted",
            "Year/Date Published": "2024",
            "Primary Topic / Predicate Crime / Typology Area": "Fraud",
            "Direct URL": "https://example.gov/extracted/",
        },
        {
            "Country/Jurisdiction": "Canada",
            "Issuing Body": "FINTRAC",
            "Document Title": "Downloaded Only",
            "Year/Date Published": "2025",
            "Primary Topic / Predicate Crime / Typology Area": "Sanctions",
            "Direct URL": "https://example.gov/downloaded/",
        },
        {
            "Country/Jurisdiction": "United Kingdom",
            "Issuing Body": "OFSI",
            "Document Title": "Missing Source",
            "Year/Date Published": "2026",
            "Primary Topic / Predicate Crime / Typology Area": "Terrorist financing",
            "Direct URL": "https://example.gov/missing",
        },
    ]
    sources_yaml = {
        "001": "https://example.gov/extracted",
        "002": "https://example.gov/downloaded",
    }

    rows = build_catalog_rows(
        catalogs,
        sources_yaml,
        {"https://example.gov/extracted"},
    )

    assert rows == [
        {
            "status": "downloaded",
            "slug": "",
            "document_title": "Downloaded Only",
            "regulator": "FINTRAC",
            "jurisdiction": "Canada",
            "issued_date": "2025",
            "source_url": "https://example.gov/downloaded",
            "primary_category": "Sanctions",
            "red_flag_count": "",
            "output_file": "",
            "extracted_at": "",
        },
        {
            "status": "not_downloaded",
            "slug": "",
            "document_title": "Missing Source",
            "regulator": "OFSI",
            "jurisdiction": "United Kingdom",
            "issued_date": "2026",
            "source_url": "https://example.gov/missing",
            "primary_category": "Terrorist financing",
            "red_flag_count": "",
            "output_file": "",
            "extracted_at": "",
        },
    ]


def test_build_registry_writes_ordered_csv_and_regenerates_from_scratch(tmp_path):
    root = tmp_path
    catalog = root / "catalog.csv"
    sources = root / "sources.yaml"
    yaml_dir = root / "data" / "source"
    yaml_dir.mkdir(parents=True)
    output = root / "red_flag_sources" / "registry.csv"

    write_catalog(
        catalog,
        [
            {
                "Region": "North America",
                "Country/Jurisdiction": "Canada",
                "Issuing Body": "FINTRAC",
                "Document Title": "Already Extracted",
                "Document Type": "Guidance",
                "Year/Date Published": "2025",
                "Primary Topic / Predicate Crime / Typology Area": "Layering",
                "Brief Summary": "Summary",
                "Direct URL": "https://example.gov/extracted",
                "Target Audience / Reporting Entity Sector": "Banks",
            },
            {
                "Region": "North America",
                "Country/Jurisdiction": "United States",
                "Issuing Body": "FinCEN",
                "Document Title": "Downloaded Only",
                "Document Type": "Advisory",
                "Year/Date Published": "2024",
                "Primary Topic / Predicate Crime / Typology Area": "Fraud",
                "Brief Summary": "Summary",
                "Direct URL": "https://example.gov/downloaded",
                "Target Audience / Reporting Entity Sector": "Banks",
            },
            {
                "Region": "Europe",
                "Country/Jurisdiction": "United Kingdom",
                "Issuing Body": "OFSI",
                "Document Title": "Missing Source",
                "Document Type": "Assessment",
                "Year/Date Published": "2026",
                "Primary Topic / Predicate Crime / Typology Area": "Sanctions",
                "Brief Summary": "Summary",
                "Direct URL": "https://example.gov/missing",
                "Target Audience / Reporting Entity Sector": "Firms",
            },
        ],
    )
    sources.write_text(
        yaml.safe_dump(
            {
                "001": {"url": "https://example.gov/extracted"},
                "002": {"url": "https://example.gov/downloaded"},
            }
        ),
        encoding="utf-8",
    )
    (yaml_dir / ".extracted_sources.yaml").write_text(
        yaml.safe_dump(
            [
                {
                    "output_file": "data/source/001.yaml",
                    "extracted_at": "2026-05-17T12:00:00Z",
                },
                {
                    "output_file": "data/source/099.yaml",
                    "extracted_at": "2026-05-17T13:00:00Z",
                },
            ]
        ),
        encoding="utf-8",
    )
    (yaml_dir / "001.yaml").write_text(
        yaml.safe_dump(
            [
                {
                    "regulatory_source": "Already Extracted",
                    "regulator": "FINTRAC",
                    "regulator_jurisdiction": "Canada",
                    "issued_date": "2025",
                    "source_url": "https://example.gov/extracted",
                    "category": "layering",
                }
            ]
        ),
        encoding="utf-8",
    )
    (yaml_dir / "099.yaml").write_text(
        yaml.safe_dump(
            [
                {
                    "regulatory_source": "Uncataloged FinCEN Source",
                    "regulator": "FinCEN",
                    "regulator_jurisdiction": "United States",
                    "issued_date": "2023",
                    "source_url": "https://fincen.gov/uncataloged",
                    "category": "fraud",
                }
            ]
        ),
        encoding="utf-8",
    )

    rows = build_registry(
        catalog_paths=[catalog],
        sources_yaml_path=sources,
        manifest_path=yaml_dir / ".extracted_sources.yaml",
        yaml_dir=yaml_dir,
        output_path=output,
    )
    first_output = output.read_text(encoding="utf-8")
    output.write_text("stale content\n", encoding="utf-8")
    build_registry(
        catalog_paths=[catalog],
        sources_yaml_path=sources,
        manifest_path=yaml_dir / ".extracted_sources.yaml",
        yaml_dir=yaml_dir,
        output_path=output,
    )

    assert [row["status"] for row in rows] == [
        "extracted",
        "extracted",
        "downloaded",
        "not_downloaded",
    ]
    assert {row["document_title"] for row in rows} == {
        "Already Extracted",
        "Uncataloged FinCEN Source",
        "Downloaded Only",
        "Missing Source",
    }
    assert output.read_text(encoding="utf-8") == first_output
    with output.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == REGISTRY_COLUMNS


def test_build_registry_requires_critical_input_files(tmp_path):
    yaml_dir = tmp_path / "data" / "source"
    yaml_dir.mkdir(parents=True)

    try:
        build_registry(
            catalog_paths=[],
            sources_yaml_path=tmp_path / "missing-sources.yaml",
            manifest_path=yaml_dir / ".extracted_sources.yaml",
            yaml_dir=yaml_dir,
            output_path=tmp_path / "registry.csv",
        )
    except FileNotFoundError as exc:
        assert "missing-sources.yaml" in str(exc)
    else:
        raise AssertionError("build_registry should require sources.yaml")

    sources = tmp_path / "sources.yaml"
    sources.write_text("{}\n", encoding="utf-8")
    try:
        build_registry(
            catalog_paths=[],
            sources_yaml_path=sources,
            manifest_path=yaml_dir / ".extracted_sources.yaml",
            yaml_dir=yaml_dir,
            output_path=tmp_path / "registry.csv",
        )
    except FileNotFoundError as exc:
        assert ".extracted_sources.yaml" in str(exc)
    else:
        raise AssertionError("build_registry should require extraction manifest")


def test_build_registry_honors_explicit_empty_catalog_list(tmp_path):
    sources = tmp_path / "sources.yaml"
    yaml_dir = tmp_path / "data" / "source"
    manifest = yaml_dir / ".extracted_sources.yaml"
    output = tmp_path / "registry.csv"
    yaml_dir.mkdir(parents=True)
    sources.write_text("{}\n", encoding="utf-8")
    manifest.write_text("[]\n", encoding="utf-8")

    rows = build_registry(
        catalog_paths=[],
        sources_yaml_path=sources,
        manifest_path=manifest,
        yaml_dir=yaml_dir,
        output_path=output,
    )

    assert rows == []
    with output.open(newline="", encoding="utf-8") as f:
        assert csv.DictReader(f).fieldnames == REGISTRY_COLUMNS
