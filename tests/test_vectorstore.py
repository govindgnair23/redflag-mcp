from __future__ import annotations

from redflag_mcp.config import EMBEDDING_DIM
from redflag_mcp.models import RedFlagRecord
from redflag_mcp.vectorstore import (
    RedFlagFilters,
    filter_red_flags,
    get_by_id,
    get_or_create_table,
    get_source,
    list_sources,
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
    regulatory_source: str | None = "FinCEN Alert",
    source_url: str | None = "https://example.com/source.pdf",
) -> RedFlagRecord:
    return RedFlagRecord(
        id=record_id,
        description=description,
        product_types=product_types or [],
        industry_types=industry_types or [],
        customer_profiles=customer_profiles or [],
        geographic_footprints=geographic_footprints or [],
        regulatory_source=regulatory_source,
        risk_level=risk_level,
        category=category,
        source_url=source_url,
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
            make_record(
                "medium", vector(1.0), risk_level="medium", category="fraud_nexus"
            ),
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


def test_search_applies_list_filters_before_semantic_ranking(tmp_vectors_dir):
    table = get_or_create_table(open_store(tmp_vectors_dir))
    non_matching_records = [
        make_record(
            f"near-miss-{number:02d}",
            vector(1.0),
            product_types=["depository"],
        )
        for number in range(60)
    ]
    matching_record = make_record(
        "filtered-match",
        vector(0.0),
        product_types=["trade_finance"],
        industry_types=["oil_and_gas"],
    )
    upsert_records(table, [*non_matching_records, matching_record])

    results = search(
        table,
        vector(1.0),
        limit=1,
        product_types=["trade_finance"],
        industry_types=["oil_and_gas"],
    )

    assert [result.id for result in results] == ["filtered-match"]
    assert results[0].score is not None


def test_empty_filter_lists_are_ignored(tmp_vectors_dir):
    table = get_or_create_table(open_store(tmp_vectors_dir))
    upsert_records(
        table, [make_record("one", vector(1.0), product_types=["depository"])]
    )

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


def test_list_sources_aggregates_records_by_source_url(tmp_vectors_dir):
    table = get_or_create_table(open_store(tmp_vectors_dir))
    upsert_records(
        table,
        [
            make_record(
                "two",
                vector(1.0),
                product_types=["trade_finance"],
                risk_level="medium",
                category="layering",
            ),
            make_record(
                "one",
                vector(1.0),
                product_types=["depository"],
                risk_level="high",
                category="fraud_nexus",
            ),
        ],
    )

    sources = list_sources(table)

    assert len(sources) == 1
    assert sources[0].source_id.startswith("url-")
    assert sources[0].source_url == "https://example.com/source.pdf"
    assert sources[0].red_flag_count == 2
    assert sources[0].red_flag_ids == ["one", "two"]
    assert sources[0].categories == ["fraud_nexus", "layering"]
    assert sources[0].risk_levels == ["high", "medium"]
    assert sources[0].product_types == ["depository", "trade_finance"]


def test_get_source_returns_bounded_vector_free_details(tmp_vectors_dir):
    table = get_or_create_table(open_store(tmp_vectors_dir))
    upsert_records(
        table,
        [
            make_record(
                f"flag-{number:02d}",
                vector(1.0),
                description=(
                    "This source describes repeated suspicious payment patterns "
                    f"for record {number}."
                ),
            )
            for number in range(12)
        ],
    )

    source_id = list_sources(table)[0].source_id
    detail = get_source(table, source_id)
    payload = detail.model_dump()

    assert detail is not None
    assert detail.red_flag_count == 12
    assert detail.red_flag_ids == [f"flag-{number:02d}" for number in range(12)]
    assert len(detail.red_flags) == 10
    assert detail.red_flags[0].id == "flag-00"
    assert detail.red_flags[0].description_snippet.endswith("record 0.")
    assert "description" not in payload["red_flags"][0]
    assert "vector" not in payload


def test_sources_without_urls_use_regulatory_source_identity(tmp_vectors_dir):
    table = get_or_create_table(open_store(tmp_vectors_dir))
    upsert_records(
        table,
        [
            make_record(
                "one",
                vector(1.0),
                regulatory_source="FinCEN Notice 2024-A",
                source_url=None,
            ),
            make_record(
                "two",
                vector(1.0),
                regulatory_source="FinCEN Notice 2024-A",
                source_url=None,
            ),
        ],
    )

    sources = list_sources(table)

    assert len(sources) == 1
    assert sources[0].source_id.startswith("name-")
    assert sources[0].regulatory_source == "FinCEN Notice 2024-A"
    assert sources[0].red_flag_ids == ["one", "two"]


def test_records_missing_source_metadata_use_unknown_source(tmp_vectors_dir):
    table = get_or_create_table(open_store(tmp_vectors_dir))
    upsert_records(
        table,
        [
            make_record(
                "unknown",
                vector(1.0),
                regulatory_source=None,
                source_url=None,
            )
        ],
    )

    sources = list_sources(table)

    assert len(sources) == 1
    assert sources[0].source_id == "unknown-source"
    assert sources[0].regulatory_source == "Unknown source"
    assert sources[0].red_flag_ids == ["unknown"]


def test_empty_table_returns_no_sources_or_source_detail(tmp_vectors_dir):
    table = get_or_create_table(open_store(tmp_vectors_dir))

    assert list_sources(table) == []
    assert get_source(table, "missing") is None


def test_filter_red_flags_applies_metadata_without_vector_search(tmp_vectors_dir):
    table = get_or_create_table(open_store(tmp_vectors_dir))
    upsert_records(
        table,
        [
            make_record(
                "match",
                vector(0.0),
                product_types=["depository"],
                risk_level="high",
                category="structuring",
            ),
            make_record(
                "miss",
                vector(1.0),
                product_types=["trade_finance"],
                risk_level="high",
                category="structuring",
            ),
        ],
    )

    results = filter_red_flags(
        table,
        filters=RedFlagFilters(
            product_types=["depository"],
            category="structuring",
            risk_level="high",
        ),
    )

    assert [result.id for result in results] == ["match"]
    assert results[0].score is None
    assert "vector" not in results[0].model_dump()


def test_filter_red_flags_uses_intersection_semantics_for_list_dimensions(
    tmp_vectors_dir,
):
    table = get_or_create_table(open_store(tmp_vectors_dir))
    upsert_records(
        table,
        [
            make_record(
                "match",
                vector(1.0),
                product_types=["depository", "trade_finance"],
                industry_types=["oil_and_gas"],
                customer_profiles=["small_business"],
                geographic_footprints=["mexico"],
            ),
            make_record(
                "miss",
                vector(1.0),
                product_types=["depository"],
                industry_types=["government_benefits"],
                customer_profiles=["small_business"],
                geographic_footprints=["mexico"],
            ),
        ],
    )

    results = filter_red_flags(
        table,
        filters=RedFlagFilters(
            product_types=["trade_finance"],
            industry_types=["oil_and_gas", "retail"],
            customer_profiles=["small_business"],
            geographic_footprints=["mexico"],
        ),
    )

    assert [result.id for result in results] == ["match"]


def test_filter_red_flags_returns_deterministic_order(tmp_vectors_dir):
    table = get_or_create_table(open_store(tmp_vectors_dir))
    upsert_records(
        table,
        [
            make_record(
                "medium-b",
                vector(1.0),
                product_types=["depository"],
                risk_level="medium",
            ),
            make_record(
                "high-b",
                vector(1.0),
                product_types=["depository"],
                risk_level="high",
            ),
            make_record(
                "high-a",
                vector(1.0),
                product_types=["depository"],
                risk_level="high",
            ),
        ],
    )

    results = filter_red_flags(
        table,
        filters=RedFlagFilters(product_types=["depository"]),
        limit=10,
    )

    assert [result.id for result in results] == ["high-a", "high-b", "medium-b"]
