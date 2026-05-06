from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

from redflag_mcp.config import EMBEDDING_DIM
from redflag_mcp.lexicalstore import create_lexical_store
from redflag_mcp.models import CorpusMetadata
from redflag_mcp.models import RedFlagRecord
from redflag_mcp.server import create_server
from redflag_mcp.tools import MAX_SEARCH_LIMIT, PRE_INGESTION_MESSAGE, RedFlagService
from redflag_mcp.vectorstore import get_or_create_table, open_store, upsert_records


class FakeModel:
    def encode(self, sentences: list[str], **kwargs: object) -> list[list[float]]:
        return [[1.0] + [0.0] * (EMBEDDING_DIM - 1) for _ in sentences]


class FailingModel:
    def encode(self, sentences: list[str], **kwargs: object) -> list[list[float]]:
        raise AssertionError("corpus mode should not encode queries")


def vector(first_value: float) -> list[float]:
    return [first_value] + [0.0] * (EMBEDDING_DIM - 1)


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
) -> RedFlagRecord:
    return RedFlagRecord(
        id=record_id,
        description=description,
        product_types=product_types or [],
        industry_types=industry_types or [],
        customer_profiles=customer_profiles or [],
        geographic_footprints=geographic_footprints or [],
        regulatory_source="FinCEN Alert FIN-2025-Alert001",
        risk_level=risk_level,
        category=category,
        source_url="https://example.com/source.pdf",
        vector=vector(1.0),
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


def seeded_corpus_service(tmp_path) -> RedFlagService:
    db_path = tmp_path / "redflags.sqlite"
    create_lexical_store(
        db_path,
        [
            make_record(
                "tbml-01",
                description="Trade-based money laundering through invoices.",
                product_types=["trade_finance"],
                industry_types=["import_export"],
                risk_level="high",
                category="trade_based_money_laundering",
            ),
            make_record(
                "benefits-01",
                description="Sponsor receives reimbursements inconsistent with profile.",
                product_types=["depository"],
                industry_types=["government_benefits"],
                risk_level="medium",
                category="fraud_nexus",
            ),
        ],
        corpus=corpus_metadata(),
        aliases={"TBML": ["trade based money laundering"]},
    )
    return RedFlagService.from_corpus_path(db_path, embedding_model=FailingModel())


def seeded_service(tmp_vectors_dir) -> RedFlagService:
    table = get_or_create_table(open_store(tmp_vectors_dir))
    upsert_records(
        table,
        [
            make_record(
                "oil-01",
                description="Small oil company wires funds near the southwest border.",
                product_types=["trade_finance"],
                industry_types=["oil_and_gas"],
                customer_profiles=["small_business"],
                geographic_footprints=["southwest_border"],
                risk_level="high",
                category="layering",
            ),
            make_record(
                "benefits-01",
                description="Sponsor receives government reimbursements inconsistent with profile.",
                product_types=["depository"],
                industry_types=["government_benefits"],
                customer_profiles=["charity_or_nonprofit"],
                geographic_footprints=["domestic_us"],
                risk_level="medium",
                category="fraud_nexus",
            ),
        ],
    )
    return RedFlagService(table=table, embedding_model=FakeModel())


def test_list_filters_returns_all_dimensions(tmp_vectors_dir):
    service = seeded_service(tmp_vectors_dir)

    response = service.list_filters()

    filters = response["filters"]
    assert filters["product_types"] == ["depository", "trade_finance"]
    assert filters["industry_types"] == ["government_benefits", "oil_and_gas"]
    assert filters["customer_profiles"] == ["charity_or_nonprofit", "small_business"]
    assert filters["geographic_footprints"] == ["domestic_us", "southwest_border"]
    assert filters["category"] == ["fraud_nexus", "layering"]
    assert filters["risk_level"] == ["high", "medium"]


def test_search_returns_clamped_sourced_results(tmp_vectors_dir):
    service = seeded_service(tmp_vectors_dir)

    response = service.search_red_flags(
        query="oil smuggling", limit=MAX_SEARCH_LIMIT + 10
    )

    assert response["limit"] == MAX_SEARCH_LIMIT
    assert len(response["results"]) == 2
    assert response["results"][0]["source_url"] == "https://example.com/source.pdf"
    assert "vector" not in response["results"][0]


def test_search_with_rich_filters_excludes_non_matching_records(tmp_vectors_dir):
    service = seeded_service(tmp_vectors_dir)

    response = service.search_red_flags(
        query="oil smuggling",
        product_types=["trade_finance"],
        industry_types=["oil_and_gas"],
        customer_profiles=["small_business"],
        geographic_footprints=["southwest_border"],
        category="layering",
        risk_level="high",
    )

    assert [result["id"] for result in response["results"]] == ["oil-01"]


def test_search_fit_explanation_mentions_matching_filter(tmp_vectors_dir):
    service = seeded_service(tmp_vectors_dir)

    response = service.search_red_flags(
        query="oil company wires",
        product_types=["trade_finance"],
    )

    result = response["results"][0]
    assert "trade_finance" in result["fit_explanation"]
    assert "Product type matches trade_finance." in result["fit_signals"]


def test_search_fit_explanation_includes_bounded_category_and_risk_signals(
    tmp_vectors_dir,
):
    service = seeded_service(tmp_vectors_dir)

    response = service.search_red_flags(
        query="oil company wires",
        product_types=["trade_finance"],
    )

    result = response["results"][0]
    assert "Category is layering." in result["fit_signals"]
    assert "Risk level is high." in result["fit_signals"]
    assert "definitely applies" not in result["fit_explanation"]


def test_search_fit_explanation_handles_missing_metadata(tmp_vectors_dir):
    table = get_or_create_table(open_store(tmp_vectors_dir))
    upsert_records(
        table,
        [
            RedFlagRecord(
                id="minimal",
                description="Unusual account activity.",
                vector=vector(1.0),
            )
        ],
    )
    service = RedFlagService(table=table, embedding_model=FakeModel())

    response = service.search_red_flags(query="unusual activity")

    assert response["results"][0]["fit_explanation"] == (
        "Semantic match to the query context."
    )
    assert response["results"][0]["fit_signals"] == [
        "Semantic match to the query context."
    ]


def test_filter_red_flags_returns_direct_metadata_matches_without_embeddings(
    tmp_vectors_dir,
):
    service = seeded_service(tmp_vectors_dir)
    service.embedding_model = FailingModel()

    response = service.filter_red_flags(
        product_types=["trade_finance"],
        industry_types=["oil_and_gas"],
        customer_profiles=["small_business"],
        geographic_footprints=["southwest_border"],
        category="layering",
        risk_level="high",
    )

    assert response["results"][0]["id"] == "oil-01"
    assert response["match_type"] == "metadata_filter"
    assert "score" not in response["results"][0]
    assert "vector" not in response["results"][0]


def test_filter_red_flags_requires_at_least_one_filter(tmp_vectors_dir):
    service = seeded_service(tmp_vectors_dir)

    response = service.filter_red_flags()

    assert response["results"] == []
    assert "Provide at least one metadata filter" in response["message"]


def test_filter_red_flags_returns_empty_without_semantic_fallback(tmp_vectors_dir):
    service = seeded_service(tmp_vectors_dir)
    service.embedding_model = FailingModel()

    response = service.filter_red_flags(product_types=["depository"], risk_level="high")

    assert response["results"] == []
    assert response["match_type"] == "metadata_filter"


def test_corpus_search_uses_lexical_store_without_embeddings(tmp_path):
    service = seeded_corpus_service(tmp_path)

    response = service.search_red_flags(query="TBML invoices")

    assert [result["id"] for result in response["results"]] == ["tbml-01"]
    assert response["corpus"]["version"] == "2026.04.29"
    assert response["corpus"]["integrity_status"] == "verified"
    assert any("TBML" in signal for signal in response["results"][0]["fit_signals"])


def test_corpus_filter_lookup_sources_include_corpus_metadata(tmp_path):
    service = seeded_corpus_service(tmp_path)

    filtered = service.filter_red_flags(product_types=["depository"])
    red_flag = service.get_red_flag("benefits-01")
    filters = service.list_filters()
    sources = service.list_sources()
    source = service.get_source(sources["sources"][0]["source_id"])

    assert [result["id"] for result in filtered["results"]] == ["benefits-01"]
    assert red_flag["red_flag"]["id"] == "benefits-01"
    assert filters["filters"]["product_types"] == ["depository", "trade_finance"]
    assert sources["source_count"] == 1
    assert source["source"]["red_flags"]
    assert filtered["corpus"]["package_id"] == "redflag-corpus-2026.04.29"
    assert red_flag["corpus"]["version"] == "2026.04.29"
    assert filters["corpus"]["version"] == "2026.04.29"
    assert sources["corpus"]["version"] == "2026.04.29"
    assert source["corpus"]["version"] == "2026.04.29"


def test_classify_red_flag_request_routes_metadata_only_context(tmp_vectors_dir):
    service = seeded_service(tmp_vectors_dir)
    service.embedding_model = FailingModel()

    response = service.classify_red_flag_request(
        query="oil smuggling",
        product_types=["trade_finance"],
        industry_types=["oil_and_gas"],
    )

    assert response["route"] == "metadata_filter"
    assert response["recommended_tool"] == "filter_red_flags"
    assert response["recommended_arguments"] == {
        "limit": 5,
        "product_types": ["trade_finance"],
        "industry_types": ["oil_and_gas"],
    }
    assert response["inferred_filters"] == {
        "product_types": ["trade_finance"],
        "industry_types": ["oil_and_gas"],
    }
    assert response["follow_up_question"] is None


def test_classify_red_flag_request_requires_two_metadata_filters(
    tmp_vectors_dir,
):
    service = seeded_service(tmp_vectors_dir)

    response = service.classify_red_flag_request(
        query="oil smuggling",
        product_types=["trade_finance"],
    )

    assert response["route"] == "needs_more_context"
    assert response["recommended_tool"] is None
    assert response["inferred_filters"] == {"product_types": ["trade_finance"]}
    assert "industry" in response["follow_up_question"]


def test_classify_red_flag_request_routes_filtered_semantic_context(
    tmp_vectors_dir,
):
    service = seeded_service(tmp_vectors_dir)

    response = service.classify_red_flag_request(
        query=(
            "trade finance customers receive third-party wires tied to "
            "unusual invoices"
        ),
        product_types=["trade_finance"],
        geographic_footprints=["southwest_border"],
        limit=50,
    )

    assert response["route"] == "filtered_semantic_search"
    assert response["recommended_tool"] == "search_red_flags"
    assert response["recommended_arguments"] == {
        "query": (
            "trade finance customers receive third-party wires tied to "
            "unusual invoices"
        ),
        "limit": MAX_SEARCH_LIMIT,
        "product_types": ["trade_finance"],
        "geographic_footprints": ["southwest_border"],
    }


def test_classify_red_flag_request_routes_direct_semantic_for_rich_narrative(
    tmp_vectors_dir,
):
    service = seeded_service(tmp_vectors_dir)

    response = service.classify_red_flag_request(
        query=(
            "small importers moving goods through Laredo with frequent "
            "third-party wires"
        )
    )

    assert response["route"] == "direct_semantic_search"
    assert response["recommended_tool"] == "search_red_flags"
    assert response["recommended_arguments"]["query"] == (
        "small importers moving goods through Laredo with frequent third-party wires"
    )
    assert response["missing_context"] == [
        "product_types",
        "industry_types",
        "customer_profiles",
        "geographic_footprints",
    ]


def test_classify_red_flag_request_routes_vague_request_to_followup(
    tmp_vectors_dir,
):
    service = seeded_service(tmp_vectors_dir)

    response = service.classify_red_flag_request(
        query="what red flags apply to my crypto product?"
    )

    assert response["route"] == "needs_more_context"
    assert response["recommended_tool"] is None
    assert response["recommended_arguments"] == {}
    assert "product/channel" in response["follow_up_question"]
    assert "customer profile" in response["follow_up_question"]


def test_get_red_flag_returns_record_without_vector(tmp_vectors_dir):
    service = seeded_service(tmp_vectors_dir)

    response = service.get_red_flag("benefits-01")

    assert response["red_flag"]["id"] == "benefits-01"
    assert response["red_flag"]["regulatory_source"] == "FinCEN Alert FIN-2025-Alert001"
    assert "vector" not in response["red_flag"]


def test_list_sources_returns_source_catalog(tmp_vectors_dir):
    service = seeded_service(tmp_vectors_dir)

    response = service.list_sources()

    assert response["source_count"] == 1
    assert response["sources"][0]["source_id"].startswith("url-")
    assert response["sources"][0]["source_url"] == "https://example.com/source.pdf"
    assert response["sources"][0]["red_flag_count"] == 2
    assert response["sources"][0]["red_flag_ids"] == ["benefits-01", "oil-01"]


def test_get_source_returns_detail_by_identifier(tmp_vectors_dir):
    service = seeded_service(tmp_vectors_dir)
    source_id = service.list_sources()["sources"][0]["source_id"]

    response = service.get_source(source_id)

    assert response["source"]["source_id"] == source_id
    assert response["source"]["red_flag_ids"] == ["benefits-01", "oil-01"]
    assert response["source"]["red_flags"][0]["id"] == "benefits-01"
    assert "vector" not in response["source"]


def test_get_source_returns_not_found_message(tmp_vectors_dir):
    service = seeded_service(tmp_vectors_dir)

    response = service.get_source("missing-source")

    assert response["message"] == "Source not found: missing-source"
    assert response["source"] is None


def test_empty_store_returns_pre_ingestion_message(tmp_vectors_dir):
    table = get_or_create_table(open_store(tmp_vectors_dir))
    service = RedFlagService(table=table, embedding_model=FakeModel())

    assert service.list_filters()["message"] == PRE_INGESTION_MESSAGE
    assert service.search_red_flags(query="anything")["results"] == []
    assert service.get_red_flag("missing")["red_flag"] is None
    assert service.list_sources()["sources"] == []
    assert service.list_sources()["message"] == PRE_INGESTION_MESSAGE
    assert service.get_source("missing")["source"] is None


def test_fastmcp_tool_metadata_includes_consultation_guidance(tmp_vectors_dir):
    app = create_server(vector_dir=tmp_vectors_dir, embedding_model=FakeModel())

    tools = asyncio.run(app.list_tools())
    by_name = {tool.name: tool for tool in tools}

    assert sorted(by_name) == [
        "classify_red_flag_request",
        "filter_red_flags",
        "get_red_flag",
        "get_source",
        "list_filters",
        "list_sources",
        "search_red_flags",
    ]
    search_description = by_name["search_red_flags"].description
    assert "vague" in search_description
    assert "product/channel" in search_description
    assert "customer profile" in search_description
    assert "transaction channel or volume" in search_description
    assert "If the request already names" in search_description
    assert "list_filters" in search_description
    assert "classify_red_flag_request" in search_description
    assert "filter_red_flags" in search_description
    assert "exact metadata" in search_description
    assert "industry_types" in by_name["search_red_flags"].inputSchema["properties"]
    classifier_description = by_name["classify_red_flag_request"].description
    assert "before searching" in classifier_description
    assert "needs_more_context" in classifier_description
    assert "filtered_semantic_search" in classifier_description
    assert "direct_semantic_search" in classifier_description
    assert "query" in by_name["classify_red_flag_request"].inputSchema["properties"]
    assert "product_types" in by_name[
        "classify_red_flag_request"
    ].inputSchema["properties"]
    assert "exact metadata" in by_name["filter_red_flags"].description
    assert "search_red_flags" in by_name["filter_red_flags"].description
    assert "source coverage" in by_name["list_sources"].description
    assert "citations" in by_name["list_sources"].description
    assert "get_red_flag" in by_name["get_source"].description


def test_server_imports_via_mcp_dev_loader_without_sys_modules_registration():
    server_path = Path(__file__).resolve().parent.parent / "src/redflag_mcp/server.py"
    module_name = "mcp_dev_server_import_test"
    spec = importlib.util.spec_from_file_location(module_name, server_path)
    assert spec is not None
    assert spec.loader is not None

    sys.modules.pop(module_name, None)
    module = importlib.util.module_from_spec(spec)

    spec.loader.exec_module(module)

    assert module.mcp.name == "redflag-mcp"
