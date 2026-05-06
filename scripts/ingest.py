#!/usr/bin/env python3
"""Ingest YAML red flag sources into the local LanceDB vector store."""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import ValidationError

load_dotenv()

# Add src to path so this script works before the package is installed.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from redflag_mcp.config import (  # noqa: E402
    CUSTOMER_PROFILES,
    GEOGRAPHIC_FOOTPRINTS,
    INDUSTRY_TYPES,
    REGULATORS,
    SOURCE_DIR,
    TRANSACTION_PATTERNS,
    TYPOLOGY_FAMILIES,
    VECTORS_DIR,
    jurisdiction_for_regulator,
)
from redflag_mcp.embeddings import EmbeddingModel, encode_documents  # noqa: E402
from redflag_mcp.models import RedFlagRecord, RedFlagSource  # noqa: E402
from redflag_mcp.vectorstore import get_or_create_table, open_store, upsert_records  # noqa: E402

LOGGER = logging.getLogger(__name__)
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_PARALLEL_WORKERS = 4
LIST_METADATA_FIELDS = (
    "product_types",
    "industry_types",
    "customer_profiles",
    "geographic_footprints",
    "typology_family",
    "transaction_patterns",
    "key_terms",
)
SCALAR_METADATA_FIELDS = ("regulatory_source", "risk_level", "category", "regulator", "issued_date")
METADATA_FIELDS = LIST_METADATA_FIELDS + SCALAR_METADATA_FIELDS
MetadataTagger = Callable[[RedFlagSource, list[str]], dict[str, Any]]


@dataclass(frozen=True)
class IngestSummary:
    source_files: int
    valid_records: int
    invalid_records: int
    enriched_records: int
    upserted_records: int


def discover_source_files(source_dir: Path = SOURCE_DIR) -> list[Path]:
    return sorted(
        path for path in source_dir.glob("*.yaml") if not path.name.startswith(".")
    )


def parse_serial_range(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d+)-(\d+)", value)
    if not match:
        raise ValueError("range must be in format NNN-NNN (e.g. 001-005)")
    start, end = int(match.group(1)), int(match.group(2))
    if start > end:
        raise ValueError("range start must be <= end")
    return start, end


def source_file_serial(path: Path) -> int | None:
    match = re.match(r"^(\d+)[_-]", path.name)
    return int(match.group(1)) if match else None


def filter_source_paths_by_range(
    paths: Sequence[Path],
    serial_range: tuple[int, int],
) -> list[Path]:
    start, end = serial_range
    return [
        path
        for path in paths
        if (serial := source_file_serial(path)) is not None and start <= serial <= end
    ]


def select_write_back_paths(
    source_paths: Sequence[Path] | None,
    *,
    source_dir: Path = SOURCE_DIR,
    serial_range: tuple[int, int] | None = None,
) -> list[Path]:
    paths = list(source_paths) if source_paths is not None else discover_source_files(source_dir)
    if serial_range is not None:
        paths = filter_source_paths_by_range(paths, serial_range)
    return paths


def load_sources(source_paths: Sequence[Path]) -> tuple[list[RedFlagSource], int]:
    sources: list[RedFlagSource] = []
    invalid = 0
    for source_path in source_paths:
        try:
            data = yaml.safe_load(source_path.read_text())
        except (OSError, yaml.YAMLError) as exc:
            LOGGER.warning("Skipping malformed source file %s: %s", source_path, exc)
            invalid += 1
            continue

        if not isinstance(data, list):
            LOGGER.warning("Skipping %s: expected top-level YAML list", source_path)
            invalid += 1
            continue

        for index, raw_entry in enumerate(data, start=1):
            if not isinstance(raw_entry, dict):
                LOGGER.warning(
                    "Skipping %s entry %s: expected mapping", source_path, index
                )
                invalid += 1
                continue
            try:
                sources.append(RedFlagSource(**raw_entry))
            except ValidationError as exc:
                entry_id = raw_entry.get("id", f"entry-{index}")
                LOGGER.warning(
                    "Skipping invalid source entry %s in %s: %s",
                    entry_id,
                    source_path,
                    exc,
                )
                invalid += 1
    return sources, invalid


def missing_metadata_fields(source: RedFlagSource) -> list[str]:
    missing: list[str] = []
    for field in LIST_METADATA_FIELDS:
        if not getattr(source, field):
            missing.append(field)
    for field in SCALAR_METADATA_FIELDS:
        if not getattr(source, field):
            missing.append(field)
    return missing


def derive_regulator_jurisdiction(source: RedFlagSource) -> RedFlagSource:
    """Derive deterministic jurisdiction metadata from regulator when possible."""
    jurisdiction = jurisdiction_for_regulator(source.regulator)
    if jurisdiction:
        if source.regulator_jurisdiction == jurisdiction:
            return source
        return source.model_copy(update={"regulator_jurisdiction": jurisdiction})
    if source.regulator:
        LOGGER.warning(
            "Record %s: regulator %r has no configured regulator_jurisdiction",
            source.id,
            source.regulator,
        )
    if source.regulator_jurisdiction:
        return source.model_copy(update={"regulator_jurisdiction": None})
    return source


def build_records(
    sources: Sequence[RedFlagSource],
    *,
    embedding_model: EmbeddingModel | None = None,
    tagger: MetadataTagger | None = None,
) -> tuple[list[RedFlagRecord], int]:
    enriched_sources: list[RedFlagSource] = []
    enriched_count = 0
    for source in sources:
        source = derive_regulator_jurisdiction(source)
        missing = missing_metadata_fields(source)
        if tagger and missing:
            patch = tagger(source, missing)
            source = merge_metadata(source, patch, missing)
            source = derive_regulator_jurisdiction(source)
            warn_free_form_values(source.id, "typology_family", source.typology_family or [], TYPOLOGY_FAMILIES)
            warn_free_form_values(source.id, "transaction_patterns", source.transaction_patterns or [], TRANSACTION_PATTERNS)
            warn_free_form_values(source.id, "regulator", [source.regulator] if source.regulator else [], REGULATORS)
            enriched_count += 1
        elif missing:
            LOGGER.warning(
                "Record %s is missing metadata fields: %s",
                source.id,
                ", ".join(missing),
            )
        enriched_sources.append(source)

    if not enriched_sources:
        return [], enriched_count

    vectors = encode_documents(
        [source.description for source in enriched_sources],
        model=embedding_model,
    )
    records = [
        RedFlagRecord.from_source(source, vector)
        for source, vector in zip(enriched_sources, vectors, strict=True)
    ]
    return records, enriched_count


def merge_metadata(
    source: RedFlagSource,
    patch: dict[str, Any],
    missing_fields: Sequence[str],
) -> RedFlagSource:
    data = source.model_dump(exclude_none=True)
    for field in missing_fields:
        if field in patch and patch[field] not in (None, ""):
            data[field] = normalize_metadata_patch_value(field, patch[field])
    return RedFlagSource(**data)


def normalize_metadata_patch_value(field: str, value: Any) -> Any:
    if field not in LIST_METADATA_FIELDS:
        return value
    if isinstance(value, list):
        return [item for item in value if item not in (None, "")]
    return [value]


def build_openai_tagger(api_key: str, model: str = DEFAULT_MODEL) -> MetadataTagger:
    from openai import OpenAI

    client = OpenAI(api_key=api_key)

    def tagger(source: RedFlagSource, missing_fields: list[str]) -> dict[str, Any]:
        messages = build_tagging_prompt(source, missing_fields)
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        content = response.choices[0].message.content or "{}"
        return json.loads(content)

    return tagger


def warn_free_form_values(
    source_id: str,
    field: str,
    values: list[str],
    vocabulary: set[str],
) -> None:
    """Log a warning for any value not present in the controlled vocabulary."""
    for value in values:
        if value not in vocabulary:
            LOGGER.warning(
                "Record %s: free-form value %r in field %r not in controlled vocabulary "
                "(review and promote to vocabulary if appropriate)",
                source_id,
                value,
                field,
            )


def build_tagging_prompt(source: RedFlagSource, missing_fields: list[str]) -> list[dict[str, str]]:
    system_prompt = f"""You are an AML compliance metadata analyst. Fill only the requested missing fields for a red flag record.

Return a JSON object with keys only from this list: {missing_fields}.
For list fields, return lists of strings. Prefer these suggested values when applicable:
- industry_types: {sorted(INDUSTRY_TYPES)}
- customer_profiles: {sorted(CUSTOMER_PROFILES)}
- geographic_footprints: {sorted(GEOGRAPHIC_FOOTPRINTS)}
- typology_family: {sorted(TYPOLOGY_FAMILIES)} — prefer values from this list; use free-form only when none apply
- transaction_patterns: {sorted(TRANSACTION_PATTERNS)} — prefer values from this list; use free-form only when none apply
- key_terms: free-form list of short, searchable phrases (instrument names, dollar thresholds, \
regulatory references, entity types — not full sentences)
- regulator: {sorted(REGULATORS)} — abbreviated issuing authority; infer from the regulatory_source value
- issued_date: ISO 8601 date string (YYYY-MM-DD or YYYY-MM or YYYY) — publication date of the source \
document; infer from the regulatory_source name if the date is embedded there

Use "high", "medium", or "low" for risk_level. Use an empty list when a requested list field is not implied. Do not rewrite the description."""

    user_prompt = json.dumps(
        {
            "id": source.id,
            "description": source.description,
            "existing_metadata": source.model_dump(exclude_none=True),
            "missing_fields": missing_fields,
        },
        indent=2,
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def write_back_yaml_sources(sources: Sequence[RedFlagSource], source_path: Path) -> None:
    """Write enriched source records back to the original YAML file.

    Rewrites the entire file with the serialized enriched records. Fields with
    None values are excluded so the output stays clean.
    """
    entries = [source.model_dump(exclude_none=True) for source in sources]
    with source_path.open("w", encoding="utf-8") as f:
        yaml.dump(entries, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    LOGGER.info("Wrote %d enriched record(s) back to %s", len(entries), source_path)


def enrich_source_for_write_back(
    source: RedFlagSource,
    *,
    tagger: MetadataTagger | None = None,
) -> tuple[RedFlagSource, bool]:
    source = derive_regulator_jurisdiction(source)
    missing = missing_metadata_fields(source)
    if tagger and missing:
        patch = tagger(source, missing)
        source = merge_metadata(source, patch, missing)
        source = derive_regulator_jurisdiction(source)
        warn_free_form_values(source.id, "typology_family", source.typology_family or [], TYPOLOGY_FAMILIES)
        warn_free_form_values(source.id, "transaction_patterns", source.transaction_patterns or [], TRANSACTION_PATTERNS)
        warn_free_form_values(source.id, "regulator", [source.regulator] if source.regulator else [], REGULATORS)
        return source, True
    return source, False


def write_back_yaml_file(
    path: Path,
    *,
    tagger: MetadataTagger | None = None,
) -> IngestSummary:
    file_sources, invalid_count = load_sources([path])
    if invalid_count:
        LOGGER.warning("Skipping write-back for %s: %d invalid record(s)", path, invalid_count)
        return IngestSummary(
            source_files=1,
            valid_records=len(file_sources),
            invalid_records=invalid_count,
            enriched_records=0,
            upserted_records=0,
        )

    enriched: list[RedFlagSource] = []
    enriched_count = 0
    for source in file_sources:
        source, changed_by_tagger = enrich_source_for_write_back(source, tagger=tagger)
        if changed_by_tagger:
            enriched_count += 1
        enriched.append(source)
    write_back_yaml_sources(enriched, path)
    LOGGER.info("Enriched %d record(s) in %s", enriched_count, path)
    return IngestSummary(
        source_files=1,
        valid_records=len(file_sources),
        invalid_records=0,
        enriched_records=enriched_count,
        upserted_records=0,
    )


def combine_summaries(summaries: Sequence[IngestSummary]) -> IngestSummary:
    return IngestSummary(
        source_files=sum(summary.source_files for summary in summaries),
        valid_records=sum(summary.valid_records for summary in summaries),
        invalid_records=sum(summary.invalid_records for summary in summaries),
        enriched_records=sum(summary.enriched_records for summary in summaries),
        upserted_records=sum(summary.upserted_records for summary in summaries),
    )


def run_write_back_yaml(
    paths: Sequence[Path],
    *,
    tagger: MetadataTagger | None = None,
    workers: int | None = None,
) -> IngestSummary:
    if not paths:
        LOGGER.info("No YAML source files selected for write-back.")
        return IngestSummary(
            source_files=0,
            valid_records=0,
            invalid_records=0,
            enriched_records=0,
            upserted_records=0,
        )

    if workers is None or workers <= 1:
        return combine_summaries(
            [write_back_yaml_file(path, tagger=tagger) for path in paths]
        )

    summaries: list[IngestSummary] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(write_back_yaml_file, path, tagger=tagger): path
            for path in paths
        }
        for future in as_completed(futures):
            path = futures[future]
            try:
                summaries.append(future.result())
            except Exception as exc:
                LOGGER.exception("Unexpected error writing back %s: %s", path, exc)
                summaries.append(
                    IngestSummary(
                        source_files=1,
                        valid_records=0,
                        invalid_records=1,
                        enriched_records=0,
                        upserted_records=0,
                    )
                )
    return combine_summaries(summaries)


def ingest_sources(
    source_paths: Sequence[Path] | None = None,
    *,
    vector_dir: Path = VECTORS_DIR,
    embedding_model: EmbeddingModel | None = None,
    tagger: MetadataTagger | None = None,
) -> IngestSummary:
    paths = list(source_paths) if source_paths is not None else discover_source_files()
    sources, invalid_count = load_sources(paths)
    records, enriched_count = build_records(
        sources,
        embedding_model=embedding_model,
        tagger=tagger,
    )
    db = open_store(vector_dir)
    table = get_or_create_table(db)
    upserted = upsert_records(table, records)
    return IngestSummary(
        source_files=len(paths),
        valid_records=len(sources),
        invalid_records=invalid_count,
        enriched_records=enriched_count,
        upserted_records=upserted,
    )


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Ingest YAML red flag sources into the local LanceDB vector store."
    )
    parser.add_argument(
        "sources",
        nargs="*",
        type=Path,
        help="Optional YAML source files. Defaults to data/source/*.yaml.",
    )
    parser.add_argument(
        "--vectors-dir",
        type=Path,
        default=VECTORS_DIR,
        help="Directory for the LanceDB vector store.",
    )
    parser.add_argument(
        "--no-auto-tag",
        action="store_true",
        help="Disable OpenAI enrichment even when OPENAI_API_KEY is available.",
    )
    parser.add_argument(
        "--write-back-yaml",
        action="store_true",
        help=(
            "Write enriched metadata back to the YAML source files. "
            "Rewrites each file with the enriched record list. "
            "Run once before building a corpus package to persist typology_family, "
            "transaction_patterns, and key_terms to the authoritative source files."
        ),
    )
    parser.add_argument(
        "--range",
        dest="serial_range",
        help=(
            "With --write-back-yaml, process only YAML files whose names start "
            "with a serial in NNN-NNN format, e.g. 001-005."
        ),
    )
    parser.add_argument(
        "--parallel",
        nargs="?",
        const=DEFAULT_PARALLEL_WORKERS,
        type=int,
        help=(
            "With --write-back-yaml, process YAML files in parallel. Optionally "
            f"pass a worker count; defaults to {DEFAULT_PARALLEL_WORKERS}."
        ),
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    tagger = None
    api_key = os.environ.get("OPENAI_API_KEY")
    if api_key and not args.no_auto_tag:
        tagger = build_openai_tagger(
            api_key,
            model=os.environ.get("OPENAI_INGEST_MODEL", DEFAULT_MODEL),
        )
    elif not args.no_auto_tag:
        LOGGER.warning(
            "OPENAI_API_KEY is not set; ingesting available metadata without auto-tagging."
        )

    source_paths: list[Path] | None = args.sources or None
    serial_range: tuple[int, int] | None = None
    if args.serial_range:
        try:
            serial_range = parse_serial_range(args.serial_range)
        except ValueError as exc:
            parser.error(str(exc))
    if args.parallel is not None and args.parallel < 1:
        parser.error("--parallel worker count must be >= 1")

    if args.write_back_yaml:
        paths = select_write_back_paths(source_paths, serial_range=serial_range)
        summary = run_write_back_yaml(paths, tagger=tagger, workers=args.parallel)
        LOGGER.info(
            "Write-back processed %s file(s), %s valid record(s), %s invalid, %s enriched.",
            summary.source_files,
            summary.valid_records,
            summary.invalid_records,
            summary.enriched_records,
        )
        return

    summary = ingest_sources(
        source_paths,
        vector_dir=args.vectors_dir,
        tagger=tagger,
    )
    LOGGER.info(
        "Ingested %s valid record(s) from %s file(s); %s invalid, %s enriched, %s upserted.",
        summary.valid_records,
        summary.source_files,
        summary.invalid_records,
        summary.enriched_records,
        summary.upserted_records,
    )


if __name__ == "__main__":
    main()
