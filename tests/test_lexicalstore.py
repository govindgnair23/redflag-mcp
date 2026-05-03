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
