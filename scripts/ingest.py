#!/usr/bin/env python3
"""Ingest YAML red flag sources into the local LanceDB vector store."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import ValidationError

load_dotenv()

# Add src to path so this script works before the package is installed.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from redflag_mcp.config import (
    CUSTOMER_PROFILES,
    GEOGRAPHIC_FOOTPRINTS,
    INDUSTRY_TYPES,
    SOURCE_DIR,
    VECTORS_DIR,
)
from redflag_mcp.embeddings import EmbeddingModel, encode_documents
from redflag_mcp.models import RedFlagRecord, RedFlagSource
from redflag_mcp.vectorstore import get_or_create_table, open_store, upsert_records

LOGGER = logging.getLogger(__name__)
DEFAULT_MODEL = "gpt-4o-mini"
LIST_METADATA_FIELDS = (
    "product_types",
    "industry_types",
    "customer_profiles",
    "geographic_footprints",
)
SCALAR_METADATA_FIELDS = ("regulatory_source", "risk_level", "category")
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


def build_records(
    sources: Sequence[RedFlagSource],
    *,
    embedding_model: EmbeddingModel | None = None,
    tagger: MetadataTagger | None = None,
) -> tuple[list[RedFlagRecord], int]:
    enriched_sources: list[RedFlagSource] = []
    enriched_count = 0
    for source in sources:
        missing = missing_metadata_fields(source)
        if tagger and missing:
            patch = tagger(source, missing)
            source = merge_metadata(source, patch, missing)
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
            data[field] = patch[field]
    return RedFlagSource(**data)


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


def build_tagging_prompt(source: RedFlagSource, missing_fields: list[str]) -> list[dict[str, str]]:
    system_prompt = f"""You are an AML compliance metadata analyst. Fill only the requested missing fields for a red flag record.

Return a JSON object with keys only from this list: {missing_fields}.
For list fields, return lists of strings. Prefer these suggested values when applicable:
- industry_types: {sorted(INDUSTRY_TYPES)}
- customer_profiles: {sorted(CUSTOMER_PROFILES)}
- geographic_footprints: {sorted(GEOGRAPHIC_FOOTPRINTS)}

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

    summary = ingest_sources(
        args.sources or None,
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
