from __future__ import annotations

import sqlite3

import pytest

from redflag_mcp.lexicalstore import (
    LexicalRedFlagFilters,
    LexicalStore,
    create_lexical_store,
)
from redflag_mcp.models import CorpusMetadata, RedFlagRecord


def make_record(
    record_id: str,
    *,
    description: str = "A red flag",
    product_types: list[str] | None = None,
    industry_types: list[str] | None = None,
    customer_profiles: list[str] | None = None,
    geographic_footprints: list[str] | None = None,
    risk_level: str = "medium",
    category: str = "fraud_nexus",
    regulatory_source: str | None = "FinCEN Alert",
    regulator: str | None = None,
    regulator_jurisdiction: str | None = None,
    issued_date: str | None = None,
    source_url: str | None = "https://example.com/source.pdf",
    typology_family: list[str] | None = None,
    transaction_patterns: list[str] | None = None,
    key_terms: list[str] | None = None,
) -> RedFlagRecord:
    return RedFlagRecord(
        id=record_id,
        description=description,
        product_types=product_types or [],
        industry_types=industry_types or [],
        customer_profiles=customer_profiles or [],
        geographic_footprints=geographic_footprints or [],
        regulatory_source=regulatory_source,
        regulator=regulator,
        regulator_jurisdiction=regulator_jurisdiction,
        issued_date=issued_date,
        risk_level=risk_level,
        category=category,
        source_url=source_url,
        typology_family=typology_family or [],
        transaction_patterns=transaction_patterns or [],
        key_terms=key_terms or [],
    )


def corpus_metadata() -> CorpusMetadata:
    return CorpusMetadata(
        version="2026.04.29",
        schema_version=1,
        build_timestamp="2026-04-29T12:00:00Z",
        package_id="redflag-corpus-2026.04.29",
        file_hashes={"redflags.sqlite": "a" * 64},
        integrity_status="verified",
        record_count=0,
        source_count=0,
    )


def test_search_expands_tbml_alias_without_embeddings(tmp_path):
    db_path = tmp_path / "redflags.sqlite"
    create_lexical_store(
        db_path,
        [
            make_record(
                "tbml-01",
                description=(
                    "Trade-based money laundering using manipulated invoices and "
                    "import export documentation."
                ),
                category="trade_based_money_laundering",
                product_types=["trade_finance"],
                industry_types=["import_export"],
            )
        ],
        corpus=corpus_metadata(),
        aliases={"TBML": ["trade based money laundering", "trade finance"]},
    )

    results = LexicalStore.open(db_path).search("TBML invoices", limit=5)

    assert [result.id for result in results] == ["tbml-01"]
    assert results[0].score is not None
    assert any("TBML" in signal for signal in results[0].fit_signals)


def test_search_expands_cvc_alias_without_embeddings(tmp_path):
    db_path = tmp_path / "redflags.sqlite"
    create_lexical_store(
        db_path,
        [
            make_record(
                "crypto-01",
                description="Convertible virtual currency mixer activity.",
                product_types=["virtual_assets"],
                industry_types=["crypto"],
                category="money_laundering",
            )
        ],
        corpus=corpus_metadata(),
        aliases={"CVC": ["convertible virtual currency", "virtual assets"]},
    )

    results = LexicalStore.open(db_path).search("CVC mixer", limit=5)

    assert [result.id for result in results] == ["crypto-01"]
    assert any("CVC" in signal for signal in results[0].fit_signals)


def test_broad_keyword_search_is_deterministically_ordered(tmp_path):
    db_path = tmp_path / "redflags.sqlite"
    records = [
        make_record("medium-b", description="Cash deposits cash deposits", risk_level="medium"),
        make_record("high-a", description="Cash deposits cash deposits", risk_level="high"),
        make_record("low-c", description="Cash deposits cash deposits", risk_level="low"),
    ]
    create_lexical_store(db_path, records, corpus=corpus_metadata(), aliases={})
    store = LexicalStore.open(db_path)

    first = [result.id for result in store.search("cash deposits", limit=3)]
    second = [result.id for result in store.search("cash deposits", limit=3)]

    assert first == second == ["high-a", "medium-b", "low-c"]


def test_filter_red_flags_uses_exact_metadata_and_no_score(tmp_path):
    db_path = tmp_path / "redflags.sqlite"
    create_lexical_store(
        db_path,
        [
            make_record(
                "match",
                product_types=["depository"],
                category="structuring",
                risk_level="high",
            ),
            make_record(
                "miss",
                product_types=["depository"],
                category="structuring",
                risk_level="medium",
            ),
        ],
        corpus=corpus_metadata(),
        aliases={},
    )

    results = LexicalStore.open(db_path).filter_red_flags(
        limit=10,
        filters=LexicalRedFlagFilters(
            product_types=["depository"],
            category="structuring",
            risk_level="high",
        ),
    )

    assert [result.id for result in results] == ["match"]
    assert results[0].score is None


def test_enriched_metadata_round_trips_through_lexical_store(tmp_path):
    db_path = tmp_path / "redflags.sqlite"
    create_lexical_store(
        db_path,
        [
            make_record(
                "enriched",
                typology_family=["trade_based_money_laundering"],
                transaction_patterns=["trade_document_manipulation"],
                key_terms=["TBML", "invoice mismatch"],
                regulator="FinCEN",
                regulator_jurisdiction="US",
                issued_date="2022-06",
            )
        ],
        corpus=corpus_metadata(),
        aliases={},
    )

    result = LexicalStore.open(db_path).get_by_id("enriched")

    assert result is not None
    assert result.typology_family == ["trade_based_money_laundering"]
    assert result.transaction_patterns == ["trade_document_manipulation"]
    assert result.key_terms == ["TBML", "invoice mismatch"]
    assert result.regulator == "FinCEN"
    assert result.regulator_jurisdiction == "US"
    assert result.issued_date == "2022-06"


def test_filter_red_flags_supports_enriched_metadata(tmp_path):
    db_path = tmp_path / "redflags.sqlite"
    create_lexical_store(
        db_path,
        [
            make_record(
                "match",
                typology_family=["trade_based_money_laundering"],
                transaction_patterns=["trade_document_manipulation"],
                regulator="AMF-France",
                regulator_jurisdiction="FR",
                issued_date="2022-06",
            ),
            make_record(
                "miss",
                typology_family=["fraud_proceeds"],
                transaction_patterns=["structuring"],
                regulator="OFAC",
                regulator_jurisdiction="US",
                issued_date="2023-01",
            ),
        ],
        corpus=corpus_metadata(),
        aliases={},
    )

    results = LexicalStore.open(db_path).filter_red_flags(
        limit=10,
        filters=LexicalRedFlagFilters(
            typology_family=["trade_based_money_laundering"],
            transaction_patterns=["trade_document_manipulation"],
            regulator_jurisdiction="FR",
            issued_after="2022",
            issued_before="2022-12",
        ),
    )

    assert [result.id for result in results] == ["match"]


def test_list_distinct_values_includes_enriched_filters(tmp_path):
    db_path = tmp_path / "redflags.sqlite"
    create_lexical_store(
        db_path,
        [
            make_record(
                "one",
                typology_family=["trade_based_money_laundering"],
                transaction_patterns=["trade_document_manipulation"],
                regulator="FinCEN",
                regulator_jurisdiction="US",
            ),
            make_record(
                "two",
                typology_family=["fraud_proceeds"],
                transaction_patterns=["structuring"],
                regulator="OFAC",
                regulator_jurisdiction="US",
            ),
        ],
        corpus=corpus_metadata(),
        aliases={},
    )

    filters = LexicalStore.open(db_path).list_distinct_values()

    assert filters["typology_family"] == ["fraud_proceeds", "trade_based_money_laundering"]
    assert filters["transaction_patterns"] == ["structuring", "trade_document_manipulation"]
    assert filters["regulator"] == ["FinCEN", "OFAC"]
    assert filters["regulator_jurisdiction"] == ["US"]


def test_empty_query_with_filters_uses_metadata_filtering(tmp_path):
    db_path = tmp_path / "redflags.sqlite"
    create_lexical_store(
        db_path,
        [
            make_record("match", product_types=["depository"], risk_level="high"),
            make_record("miss", product_types=["trade_finance"], risk_level="high"),
        ],
        corpus=corpus_metadata(),
        aliases={},
    )

    results = LexicalStore.open(db_path).search(
        "",
        product_types=["depository"],
        risk_level="high",
    )

    assert [result.id for result in results] == ["match"]
    assert results[0].score is None


def test_no_lexical_matches_returns_empty_results_with_corpus_metadata(tmp_path):
    db_path = tmp_path / "redflags.sqlite"
    create_lexical_store(
        db_path,
        [make_record("one", description="Cash deposits")],
        corpus=corpus_metadata(),
        aliases={},
    )
    store = LexicalStore.open(db_path)

    assert store.search("nonexistent phrase") == []
    assert store.corpus.version == "2026.04.29"


def test_opening_wrong_schema_version_fails(tmp_path):
    db_path = tmp_path / "bad.sqlite"
    with sqlite3.connect(db_path) as connection:
        connection.execute("CREATE TABLE corpus_metadata (key TEXT PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO corpus_metadata VALUES ('schema_version', '999')")

    with pytest.raises(ValueError, match="Unsupported corpus schema version"):
        LexicalStore.open(db_path)


def test_source_ids_match_vectorstore_url_hash_behavior(tmp_path):
    db_path = tmp_path / "redflags.sqlite"
    create_lexical_store(
        db_path,
        [
            make_record("two", risk_level="medium", category="layering"),
            make_record("one", risk_level="high", category="fraud_nexus"),
        ],
        corpus=corpus_metadata(),
        aliases={},
    )

    sources = LexicalStore.open(db_path).list_sources()
    detail = LexicalStore.open(db_path).get_source(sources[0].source_id)

    assert len(sources) == 1
    assert sources[0].source_id.startswith("url-")
    assert sources[0].red_flag_ids == ["one", "two"]
    assert detail is not None
    assert len(detail.red_flags) == 2
