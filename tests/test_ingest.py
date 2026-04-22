from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from ingest import (  # noqa: E402
    build_records,
    discover_source_files,
    ingest_sources,
    load_sources,
    missing_metadata_fields,
)
from redflag_mcp.config import EMBEDDING_DIM  # noqa: E402
from redflag_mcp.models import RedFlagSource  # noqa: E402
from redflag_mcp.vectorstore import get_or_create_table, list_distinct_values, open_store  # noqa: E402


class FakeModel:
    def encode(self, sentences: list[str], **kwargs: object) -> list[list[float]]:
        return [[float(index)] + [0.0] * (EMBEDDING_DIM - 1) for index, _ in enumerate(sentences)]


TARGET_FILES = [
    Path("data/source/001_federal_child_nutrition_fraud.yaml"),
    Path("data/source/002_oil_smuggling_cartels.yaml"),
    Path("data/source/003_bulk_cash_smuggling_repatriation.yaml"),
]


def test_load_target_yaml_files_produces_37_valid_records():
    sources, invalid = load_sources(TARGET_FILES)

    assert len(sources) == 37
    assert invalid == 0


def test_complete_metadata_does_not_trigger_tagger():
    source = RedFlagSource(
        id="complete-01",
        description="Complete record",
        product_types=["depository"],
        industry_types=["retail"],
        customer_profiles=["cash_intensive_business"],
        geographic_footprints=["domestic_us"],
        regulatory_source="FinCEN Alert",
        risk_level="high",
        category="structuring",
    )

    def tagger(_source: RedFlagSource, _missing: list[str]) -> dict:
        raise AssertionError("tagger should not be called for complete metadata")

    records, enriched_count = build_records([source], embedding_model=FakeModel(), tagger=tagger)

    assert enriched_count == 0
    assert records[0].industry_types == ["retail"]


def test_missing_rich_metadata_is_enriched_with_mocked_tagger():
    source = RedFlagSource(
        id="missing-01",
        description="Small oil company wires funds near the southwest border",
        product_types=["depository"],
        regulatory_source="FinCEN Alert",
        risk_level="medium",
        category="fraud_nexus",
    )

    def tagger(_source: RedFlagSource, missing: list[str]) -> dict:
        assert "industry_types" in missing
        return {
            "industry_types": ["oil_and_gas"],
            "customer_profiles": ["small_business"],
            "geographic_footprints": ["southwest_border"],
        }

    records, enriched_count = build_records([source], embedding_model=FakeModel(), tagger=tagger)

    assert enriched_count == 1
    assert records[0].industry_types == ["oil_and_gas"]
    assert records[0].customer_profiles == ["small_business"]
    assert records[0].geographic_footprints == ["southwest_border"]


def test_explicit_source_selection_excludes_other_yaml(tmp_path, tmp_vectors_dir):
    selected = tmp_path / "selected.yaml"
    other = tmp_path / "other.yaml"
    selected.write_text(
        yaml.safe_dump([{"id": "selected-01", "description": "Selected"}])
    )
    other.write_text(yaml.safe_dump([{"id": "other-01", "description": "Other"}]))

    summary = ingest_sources([selected], vector_dir=tmp_vectors_dir, embedding_model=FakeModel())

    table = get_or_create_table(open_store(tmp_vectors_dir))
    assert summary.valid_records == 1
    assert table.count_rows() == 1
    assert list_distinct_values(table)["category"] == []


def test_missing_api_key_path_preserves_metadata_and_logs_warning(caplog):
    source = RedFlagSource(id="minimal-01", description="Minimal")

    with caplog.at_level(logging.WARNING):
        records, enriched_count = build_records([source], embedding_model=FakeModel())

    assert enriched_count == 0
    assert records[0].industry_types == []
    assert "missing metadata fields" in caplog.text


def test_invalid_records_are_reported_without_aborting_other_files(tmp_path):
    valid = tmp_path / "valid.yaml"
    invalid = tmp_path / "invalid.yaml"
    malformed = tmp_path / "malformed.yaml"
    valid.write_text(yaml.safe_dump([{"id": "valid-01", "description": "Valid"}]))
    invalid.write_text(
        yaml.safe_dump(
            [{"id": "invalid-01", "description": "Invalid", "risk_level": "critical"}]
        )
    )
    malformed.write_text("[")

    sources, invalid_count = load_sources([invalid, malformed, valid])

    assert [source.id for source in sources] == ["valid-01"]
    assert invalid_count == 2


def test_ingestion_twice_keeps_one_row_per_id(tmp_path, tmp_vectors_dir):
    source = tmp_path / "source.yaml"
    source.write_text(yaml.safe_dump([{"id": "one-01", "description": "One"}]))

    ingest_sources([source], vector_dir=tmp_vectors_dir, embedding_model=FakeModel())
    ingest_sources([source], vector_dir=tmp_vectors_dir, embedding_model=FakeModel())

    table = get_or_create_table(open_store(tmp_vectors_dir))
    assert table.count_rows() == 1


def test_discover_source_files_excludes_hidden_manifest(tmp_path):
    visible = tmp_path / "visible.yaml"
    hidden = tmp_path / ".extracted_sources.yaml"
    visible.write_text("[]")
    hidden.write_text("[]")

    assert discover_source_files(tmp_path) == [visible]


def test_missing_metadata_fields_detects_empty_lists_and_scalars():
    source = RedFlagSource(
        id="missing-01",
        description="Missing",
        product_types=[],
        risk_level="medium",
    )

    missing = missing_metadata_fields(source)

    assert "product_types" in missing
    assert "industry_types" in missing
    assert "risk_level" not in missing
