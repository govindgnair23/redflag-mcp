#!/usr/bin/env python3
"""Build a unified registry of red-flag source extraction status."""

from __future__ import annotations

import argparse
import csv
import logging
from collections import Counter
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RED_FLAG_SOURCES_DIR = PROJECT_ROOT / "red_flag_sources"
SOURCE_DIR = PROJECT_ROOT / "data" / "source"

DEFAULT_CATALOG_PATHS = [
    RED_FLAG_SOURCES_DIR / "Global_AML_CFT_Sanctions_Red_Flag_Catalog.csv",
    RED_FLAG_SOURCES_DIR / "Additional_sources_05132026.csv",
]
DEFAULT_SOURCES_YAML_PATH = RED_FLAG_SOURCES_DIR / "sources.yaml"
DEFAULT_MANIFEST_PATH = SOURCE_DIR / ".extracted_sources.yaml"
DEFAULT_REGISTRY_PATH = RED_FLAG_SOURCES_DIR / "registry.csv"
LOGGER = logging.getLogger(__name__)
REGISTRY_COLUMNS = [
    "status",
    "slug",
    "document_title",
    "regulator",
    "jurisdiction",
    "issued_date",
    "source_url",
    "primary_category",
    "red_flag_count",
    "output_file",
    "extracted_at",
]


def normalize_url(url: str) -> str:
    """Normalize URLs enough for catalog/source registry comparisons."""
    return url.strip().rstrip("/")


def load_catalogs(catalog_paths: list[Path]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in catalog_paths:
        if not path.exists():
            continue
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                normalized = {key: value or "" for key, value in row.items()}
                normalized["Direct URL"] = normalize_url(normalized.get("Direct URL", ""))
                rows.append(normalized)
    return rows


def load_sources_yaml(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        return {}

    sources: dict[str, str] = {}
    for serial_key, entry in data.items():
        if isinstance(entry, dict):
            url = entry.get("url", "")
        else:
            url = str(entry or "")
        sources[str(serial_key)] = normalize_url(url)
    return sources


def load_extraction_manifest(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, list):
        return {}

    manifest: dict[str, str] = {}
    for entry in data:
        if not isinstance(entry, dict):
            continue
        output_file = str(entry.get("output_file", ""))
        if output_file:
            manifest[output_file] = str(entry.get("extracted_at", ""))
    return manifest


def build_extracted_rows(yaml_dir: Path, manifest: dict[str, str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if not yaml_dir.exists():
        return rows

    for path in sorted(yaml_dir.glob("*.yaml")):
        if path.name.startswith("."):
            continue
        with path.open(encoding="utf-8") as f:
            flags = yaml.safe_load(f)
        if not isinstance(flags, list) or not flags:
            continue

        first = flags[0] if isinstance(flags[0], dict) else {}
        categories = [
            flag.get("category", "")
            for flag in flags
            if isinstance(flag, dict) and flag.get("category")
        ]
        primary_category = Counter(categories).most_common(1)[0][0] if categories else ""
        output_file = f"data/source/{path.name}"

        rows.append(
            {
                "status": "extracted",
                "slug": path.stem,
                "document_title": str(first.get("regulatory_source", "")),
                "regulator": str(first.get("regulator", "")),
                "jurisdiction": str(first.get("regulator_jurisdiction", "")),
                "issued_date": str(first.get("issued_date", "")),
                "source_url": normalize_url(str(first.get("source_url", ""))),
                "primary_category": primary_category,
                "red_flag_count": str(len(flags)),
                "output_file": output_file,
                "extracted_at": manifest.get(output_file, ""),
            }
        )
    return rows


def build_catalog_rows(
    catalogs: list[dict[str, str]],
    sources_yaml: dict[str, str],
    extracted_urls: set[str],
) -> list[dict[str, str]]:
    downloaded_urls = {normalize_url(url) for url in sources_yaml.values() if url}
    extracted_url_set = {normalize_url(url) for url in extracted_urls if url}
    rows: list[dict[str, str]] = []

    for catalog in catalogs:
        source_url = normalize_url(catalog.get("Direct URL", ""))
        if not source_url or source_url in extracted_url_set:
            continue

        rows.append(
            {
                "status": "downloaded" if source_url in downloaded_urls else "not_downloaded",
                "slug": "",
                "document_title": catalog.get("Document Title", ""),
                "regulator": catalog.get("Issuing Body", ""),
                "jurisdiction": catalog.get("Country/Jurisdiction", ""),
                "issued_date": catalog.get("Year/Date Published", ""),
                "source_url": source_url,
                "primary_category": catalog.get(
                    "Primary Topic / Predicate Crime / Typology Area",
                    catalog.get("Primary Topic", ""),
                ),
                "red_flag_count": "",
                "output_file": "",
                "extracted_at": "",
            }
        )
    return rows


def sort_registry_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    status_order = {"extracted": 0, "downloaded": 1, "not_downloaded": 2}
    return sorted(
        rows,
        key=lambda row: (
            status_order.get(row["status"], 99),
            row.get("slug") or row.get("document_title", ""),
        ),
    )


def write_registry(rows: list[dict[str, str]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=REGISTRY_COLUMNS)
        writer.writeheader()
        writer.writerows([{column: row.get(column, "") for column in REGISTRY_COLUMNS} for row in rows])


def build_registry(
    catalog_paths: list[Path] | None = None,
    sources_yaml_path: Path = DEFAULT_SOURCES_YAML_PATH,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    yaml_dir: Path = SOURCE_DIR,
    output_path: Path = DEFAULT_REGISTRY_PATH,
) -> list[dict[str, str]]:
    for path in (sources_yaml_path, manifest_path):
        if not path.exists():
            raise FileNotFoundError(f"Required registry input is missing: {path}")

    catalogs = load_catalogs(DEFAULT_CATALOG_PATHS if catalog_paths is None else catalog_paths)
    sources_yaml = load_sources_yaml(sources_yaml_path)
    manifest = load_extraction_manifest(manifest_path)
    extracted_rows = build_extracted_rows(yaml_dir, manifest)
    extracted_urls = {row["source_url"] for row in extracted_rows if row["source_url"]}
    catalog_rows = build_catalog_rows(catalogs, sources_yaml, extracted_urls)
    rows = sort_registry_rows(extracted_rows + catalog_rows)
    write_registry(rows, output_path)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build red_flag_sources/registry.csv from catalogs and extracted sources."
    )
    parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    rows = build_registry()
    LOGGER.info("Wrote %s rows to %s", len(rows), DEFAULT_REGISTRY_PATH)


if __name__ == "__main__":
    main()
