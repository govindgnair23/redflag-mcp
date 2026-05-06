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


def test_current_yaml_validates():
    path = (
        Path(__file__).resolve().parent.parent
        / "data/source/002_oil_smuggling_cartels.yaml"
    )
    records = yaml.safe_load(path.read_text())

    parsed = [RedFlagSource(**record) for record in records]

    assert len(parsed) == 14


def test_enriched_yaml_metadata_validates_and_is_preserved():
    source = RedFlagSource(
        id="enriched-01",
        description="Trade invoices are inconsistent with shipping records.",
        typology_family=["trade_based_money_laundering"],
        transaction_patterns=["over_invoicing", "invoice_mismatch"],
        key_terms=["TBML", "trade finance"],
    )

    payload = source.model_dump()

    assert payload["typology_family"] == ["trade_based_money_laundering"]
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


def test_source_accepts_enriched_metadata():
    source = RedFlagSource(
        id="enriched-01",
        description="Customer uses TBML invoices to layer illicit funds.",
        typology_family=["trade_based_money_laundering"],
        transaction_patterns=["trade_document_manipulation", "rapid_fund_movement"],
        key_terms=["invoice manipulation", "TBML", "import/export"],
    )

    assert source.typology_family == ["trade_based_money_laundering"]
    assert source.transaction_patterns == ["trade_document_manipulation", "rapid_fund_movement"]
    assert source.key_terms == ["invoice manipulation", "TBML", "import/export"]


def test_current_yaml_without_enriched_fields_validates():
    path = (
        Path(__file__).resolve().parent.parent
        / "data/source/001_federal_child_nutrition_fraud.yaml"
    )
    records = yaml.safe_load(path.read_text())

    parsed = [RedFlagSource(**record) for record in records]

    assert len(parsed) == 13
    assert parsed[0].typology_family is None
    assert parsed[0].transaction_patterns is None
    assert parsed[0].key_terms is None


def test_record_from_source_normalizes_enriched_lists_to_empty():
    source = RedFlagSource(id="minimal-02", description="Minimal red flag, no enrichment")
    vector = [0.0] * EMBEDDING_DIM

    record = RedFlagRecord.from_source(source, vector)

    assert record.typology_family == []
    assert record.transaction_patterns == []
    assert record.key_terms == []


def test_result_carries_enriched_fields_through_to_result():
    source = RedFlagSource(
        id="enriched-02",
        description="Crypto mixing to layer funds.",
        typology_family=["crypto_asset_money_laundering"],
        transaction_patterns=["cryptocurrency_mixing"],
        key_terms=["crypto mixer", "virtual asset"],
    )
    vector = [0.0] * EMBEDDING_DIM
    record = RedFlagRecord.from_source(source, vector)

    result = record.to_result()

    assert result.typology_family == ["crypto_asset_money_laundering"]
    assert result.transaction_patterns == ["cryptocurrency_mixing"]
    assert result.key_terms == ["crypto mixer", "virtual asset"]


def test_enriched_fields_accept_empty_lists():
    source = RedFlagSource(
        id="empty-01",
        description="Red flag with empty enrichment lists.",
        typology_family=[],
        transaction_patterns=[],
        key_terms=[],
    )
    vector = [0.0] * EMBEDDING_DIM
    record = RedFlagRecord.from_source(source, vector)

    payload = record.model_dump(exclude_none=True)

    assert payload["typology_family"] == []
    assert payload["transaction_patterns"] == []
    assert payload["key_terms"] == []


def test_typology_family_accepts_free_form_values():
    """Advisory vocabulary — free-form values must not raise ValidationError."""
    source = RedFlagSource(
        id="freeform-01",
        description="Exotic typology not yet in the vocabulary.",
        typology_family=["some_new_typology_not_in_vocabulary"],
    )
    assert source.typology_family == ["some_new_typology_not_in_vocabulary"]


def test_transaction_patterns_accepts_free_form_values():
    """Advisory vocabulary — free-form values must not raise ValidationError."""
    source = RedFlagSource(
        id="freeform-02",
        description="Novel transaction pattern.",
        transaction_patterns=["some_new_pattern_not_in_vocabulary"],
    )
    assert source.transaction_patterns == ["some_new_pattern_not_in_vocabulary"]


def test_source_accepts_regulator_field():
    source = RedFlagSource(id="reg-01", description="Test", regulator="FinCEN")
    assert source.regulator == "FinCEN"


def test_source_accepts_optional_regulator_jurisdiction_field():
    source = RedFlagSource(
        id="reg-jurisdiction-01",
        description="Test",
        regulator="AMF-France",
        regulator_jurisdiction="FR",
    )

    assert source.regulator_jurisdiction == "FR"


def test_source_accepts_unknown_regulator_without_error():
    from pydantic import ValidationError as _VE
    try:
        source = RedFlagSource(id="reg-02", description="Test", regulator="SomeUnknownAgency")
        assert source.regulator == "SomeUnknownAgency"
    except _VE:
        pytest.fail("Unknown regulator should not raise ValidationError (advisory vocab)")


def test_source_accepts_issued_date_field():
    source = RedFlagSource(id="date-01", description="Test", issued_date="2022-03-07")
    assert source.issued_date == "2022-03-07"


def test_record_from_source_carries_regulator_and_date():
    source = RedFlagSource(
        id="carry-01",
        description="Test",
        regulator="OFAC",
        regulator_jurisdiction="US",
        issued_date="2023-06",
    )
    vector = [0.0] * EMBEDDING_DIM
    record = RedFlagRecord.from_source(source, vector)
    assert record.regulator == "OFAC"
    assert record.regulator_jurisdiction == "US"
    assert record.issued_date == "2023-06"


def test_result_carries_regulator_and_date():
    source = RedFlagSource(
        id="result-carry-01",
        description="Test",
        regulator="FATF",
        regulator_jurisdiction="FATF",
        issued_date="2021",
    )
    vector = [0.0] * EMBEDDING_DIM
    record = RedFlagRecord.from_source(source, vector)
    result = record.to_result()
    assert result.regulator == "FATF"
    assert result.regulator_jurisdiction == "FATF"
    assert result.issued_date == "2021"
    assert "vector" not in result.model_dump()


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
