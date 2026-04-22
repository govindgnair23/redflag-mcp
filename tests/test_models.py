from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from redflag_mcp.config import EMBEDDING_DIM
from redflag_mcp.models import RedFlagRecord, RedFlagSource


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
