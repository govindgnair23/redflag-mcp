from __future__ import annotations

from redflag_mcp.config import EMBEDDING_DIM
from redflag_mcp.models import RedFlagRecord
from redflag_mcp.vectorstore import (
    get_by_id,
    get_or_create_table,
    list_distinct_values,
    open_store,
    search,
    upsert_records,
)


def make_record(
    record_id: str,
    vector: list[float],
    *,
    description: str = "A red flag",
    product_types: list[str] | None = None,
    industry_types: list[str] | None = None,
    customer_profiles: list[str] | None = None,
    geographic_footprints: list[str] | None = None,
    risk_level: str = "medium",
    category: str = "fraud_nexus",
) -> RedFlagRecord:
    return RedFlagRecord(
        id=record_id,
        description=description,
        product_types=product_types or [],
        industry_types=industry_types or [],
        customer_profiles=customer_profiles or [],
        geographic_footprints=geographic_footprints or [],
        regulatory_source="FinCEN Alert",
        risk_level=risk_level,
        category=category,
        source_url="https://example.com/source.pdf",
        vector=vector,
    )


def vector(first_value: float) -> list[float]:
    return [first_value] + [0.0] * (EMBEDDING_DIM - 1)


def test_upsert_updates_existing_record(tmp_vectors_dir):
    table = get_or_create_table(open_store(tmp_vectors_dir))
    upsert_records(table, [make_record("one", vector(1.0), description="Old")])
    upsert_records(table, [make_record("one", vector(1.0), description="New")])

    assert table.count_rows() == 1
    assert get_by_id(table, "one").description == "New"


def test_search_returns_ranked_results(tmp_vectors_dir):
    table = get_or_create_table(open_store(tmp_vectors_dir))
    upsert_records(
        table,
        [
            make_record("near", vector(1.0), description="Near match"),
            make_record("far", vector(0.0), description="Far match"),
        ],
    )

    results = search(table, vector(1.0), limit=2)

    assert [result.id for result in results] == ["near", "far"]
    assert results[0].score is not None


def test_search_applies_scalar_filters(tmp_vectors_dir):
    table = get_or_create_table(open_store(tmp_vectors_dir))
    upsert_records(
        table,
        [
            make_record("high", vector(1.0), risk_level="high", category="layering"),
            make_record("medium", vector(1.0), risk_level="medium", category="fraud_nexus"),
        ],
    )

    results = search(table, vector(1.0), risk_level="high", category="layering")

    assert [result.id for result in results] == ["high"]


def test_search_applies_list_filters(tmp_vectors_dir):
    table = get_or_create_table(open_store(tmp_vectors_dir))
    upsert_records(
        table,
        [
            make_record(
                "oil",
                vector(1.0),
                product_types=["trade_finance"],
                industry_types=["oil_and_gas"],
                customer_profiles=["small_business"],
                geographic_footprints=["southwest_border"],
            ),
            make_record(
                "benefits",
                vector(1.0),
                product_types=["depository"],
                industry_types=["government_benefits"],
                customer_profiles=["charity_or_nonprofit"],
                geographic_footprints=["domestic_us"],
            ),
        ],
    )

    results = search(
        table,
        vector(1.0),
        product_types=["trade_finance"],
        industry_types=["oil_and_gas"],
        customer_profiles=["small_business"],
        geographic_footprints=["southwest_border"],
    )

    assert [result.id for result in results] == ["oil"]


def test_empty_filter_lists_are_ignored(tmp_vectors_dir):
    table = get_or_create_table(open_store(tmp_vectors_dir))
    upsert_records(table, [make_record("one", vector(1.0), product_types=["depository"])])

    results = search(table, vector(1.0), product_types=[])

    assert [result.id for result in results] == ["one"]


def test_empty_table_search_returns_empty(tmp_vectors_dir):
    table = get_or_create_table(open_store(tmp_vectors_dir))

    assert search(table, vector(1.0)) == []


def test_list_distinct_values_returns_sorted_filters(tmp_vectors_dir):
    table = get_or_create_table(open_store(tmp_vectors_dir))
    upsert_records(
        table,
        [
            make_record(
                "one",
                vector(1.0),
                product_types=["depository", "trade_finance"],
                industry_types=["oil_and_gas"],
                customer_profiles=["small_business"],
                geographic_footprints=["mexico"],
                risk_level="high",
                category="layering",
            ),
            make_record(
                "two",
                vector(0.0),
                product_types=["depository"],
                industry_types=["government_benefits"],
                customer_profiles=["charity_or_nonprofit"],
                geographic_footprints=["domestic_us"],
                risk_level="medium",
                category="fraud_nexus",
            ),
        ],
    )

    filters = list_distinct_values(table)

    assert filters["product_types"] == ["depository", "trade_finance"]
    assert filters["industry_types"] == ["government_benefits", "oil_and_gas"]
    assert filters["customer_profiles"] == ["charity_or_nonprofit", "small_business"]
    assert filters["geographic_footprints"] == ["domestic_us", "mexico"]
    assert filters["risk_level"] == ["high", "medium"]
    assert filters["category"] == ["fraud_nexus", "layering"]
