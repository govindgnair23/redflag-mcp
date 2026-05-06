from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from redflag_mcp.config import EMBEDDING_DIM
from redflag_mcp.models import (
    CorpusMetadata,
    RedFlagRecord,
    RedFlagSource,
    RedFlagSourceDetail,
    RedFlagSourceSummary,
    SourceReleaseMetadata,
    build_source_manifest,
)


def test_source_accepts_rich_metadata():
    source = RedFlagSource(
        id="rich-01",
        description="A customer suddenly receives government reimbursements.",
        product_types=["depository"],
        industry_types=["government_benefits"],
        customer_profiles=["charity_or_nonprofit"],
        geographic_footprints=["domestic_us"],
        regulatory_source="FinCEN Alert",
        risk_level="medium",
        category="fraud_nexus",
        simulation_type="2B",
        source_url="https://example.com/source.pdf",
    )

    assert source.industry_types == ["government_benefits"]
    assert source.customer_profiles == ["charity_or_nonprofit"]
    assert source.geographic_footprints == ["domestic_us"]


def test_current_yaml_without_rich_metadata_validates():
    path = (
        Path(__file__).resolve().parent.parent
        / "data/source/002_oil_smuggling_cartels.yaml"
    )
    records = yaml.safe_load(path.read_text())

    parsed = [RedFlagSource(**record) for record in records]

    assert len(parsed) == 14
    assert parsed[0].industry_types is None


def test_enriched_yaml_metadata_validates_and_is_preserved():
    source = RedFlagSource(
        id="enriched-01",
        description="Trade invoices are inconsistent with shipping records.",
        typology_family="trade_based_money_laundering",
        transaction_patterns=["over_invoicing", "invoice_mismatch"],
        key_terms=["TBML", "trade finance"],
    )

    payload = source.model_dump()

    assert payload["typology_family"] == "trade_based_money_laundering"
    assert payload["transaction_patterns"] == ["over_invoicing", "invoice_mismatch"]
    assert payload["key_terms"] == ["TBML", "trade finance"]


def test_corpus_metadata_validates_and_serializes():
    metadata = CorpusMetadata(
        version="2026.04.29",
        schema_version=1,
        build_timestamp="2026-04-29T12:00:00Z",
        package_id="redflag-corpus-2026.04.29",
        file_hashes={
            "manifest.json": "a" * 64,
            "redflags.sqlite": "b" * 64,
        },
        integrity_status="verified",
        record_count=3,
        source_count=2,
    )

    payload = metadata.model_dump()

    assert payload["version"] == "2026.04.29"
    assert payload["schema_version"] == 1
    assert payload["file_hashes"]["redflags.sqlite"] == "b" * 64
    assert payload["integrity_status"] == "verified"


def test_source_metadata_merges_with_source_registry():
    metadata = {
        "001": SourceReleaseMetadata(
            title="Federal Child Nutrition Program Fraud Alert",
            authority="FinCEN",
            jurisdiction="US",
            publication_date="2026-01",
            redistribution_status="url_only",
        )
    }
    registry = {"001": {"url": "https://example.com/fincen-alert.pdf"}}

    manifest = build_source_manifest(metadata, registry)

    assert manifest["001"].title == "Federal Child Nutrition Program Fraud Alert"
    assert manifest["001"].source_url == "https://example.com/fincen-alert.pdf"
    assert manifest["001"].redistribution_status == "url_only"
    assert manifest["001"].bundle_source_asset is False


def test_missing_source_metadata_defaults_to_url_only_manifest_entry():
    manifest = build_source_manifest(
        {},
        {"002": {"url": "https://example.com/source.pdf"}},
    )

    assert manifest["002"].title is None
    assert manifest["002"].source_url == "https://example.com/source.pdf"
    assert manifest["002"].redistribution_status == "url_only"
    assert manifest["002"].bundle_source_asset is False


def test_source_metadata_unknown_registry_key_is_rejected():
    metadata = {
        "999": SourceReleaseMetadata(
            title="Unknown Source",
            authority="FinCEN",
            jurisdiction="US",
            redistribution_status="url_only",
        )
    }

    with pytest.raises(ValueError, match="unknown source keys"):
        build_source_manifest(metadata, {"001": {"url": "https://example.com/one.pdf"}})


def test_record_from_source_normalizes_missing_lists_to_empty():
    source = RedFlagSource(id="minimal-01", description="Minimal red flag")
    vector = [0.0] * EMBEDDING_DIM

    record = RedFlagRecord.from_source(source, vector)

    assert record.product_types == []
    assert record.industry_types == []
    assert record.customer_profiles == []
    assert record.geographic_footprints == []


def test_invalid_risk_level_rejected():
    with pytest.raises(ValidationError):
        RedFlagSource(
            id="invalid-01",
            description="Bad risk level",
            risk_level="critical",
        )


def test_invalid_simulation_type_rejected():
    with pytest.raises(ValidationError):
        RedFlagSource(
            id="invalid-01",
            description="Bad simulation type",
            simulation_type="9Z",
        )


def test_record_to_result_omits_vector_and_preserves_citation_metadata():
    record = RedFlagRecord(
        id="record-01",
        description="Cash deposits inconsistent with expected activity.",
        product_types=["depository"],
        industry_types=["retail"],
        customer_profiles=["cash_intensive_business"],
        geographic_footprints=["domestic_us"],
        regulatory_source="FinCEN Alert",
        risk_level="high",
        category="structuring",
        source_url="https://example.com/source.pdf",
        vector=[0.1] * EMBEDDING_DIM,
    )

    result = record.to_result(score=0.88)
    payload = result.model_dump()

    assert "vector" not in payload
    assert payload["regulatory_source"] == "FinCEN Alert"
    assert payload["source_url"] == "https://example.com/source.pdf"
    assert payload["score"] == 0.88


def test_result_accepts_bounded_fit_explanation_fields():
    result = RedFlagRecord(
        id="record-01",
        description="Cash deposits inconsistent with expected activity.",
        vector=[0.1] * EMBEDDING_DIM,
    ).to_result()
    result.fit_signals = ["Semantic match to query context."]
    result.fit_explanation = "Semantic match to query context."

    payload = result.model_dump(exclude_none=True)

    assert payload["fit_signals"] == ["Semantic match to query context."]
    assert payload["fit_explanation"] == "Semantic match to query context."
    assert "vector" not in payload


def test_source_summary_and_detail_models_are_vector_free():
    summary = RedFlagSourceSummary(
        source_id="source-example",
        regulatory_source="FinCEN Alert",
        source_url="https://example.com/source.pdf",
        red_flag_count=2,
        categories=["fraud_nexus"],
        risk_levels=["high", "medium"],
        product_types=["depository"],
        red_flag_ids=["one", "two"],
    )
    detail = RedFlagSourceDetail(
        **summary.model_dump(),
        industry_types=["government_benefits"],
        customer_profiles=["charity_or_nonprofit"],
        geographic_footprints=["domestic_us"],
        red_flags=[
            {
                "id": "one",
                "description_snippet": "Government payments inconsistent with profile.",
                "category": "fraud_nexus",
                "risk_level": "high",
            }
        ],
    )

    assert "vector" not in summary.model_dump()
    assert "vector" not in detail.model_dump()
    assert detail.red_flags[0].description_snippet == (
        "Government payments inconsistent with profile."
    )
