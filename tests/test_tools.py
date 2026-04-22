from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

from redflag_mcp.config import EMBEDDING_DIM
from redflag_mcp.models import RedFlagRecord
from redflag_mcp.server import create_server
from redflag_mcp.tools import MAX_SEARCH_LIMIT, PRE_INGESTION_MESSAGE, RedFlagService
from redflag_mcp.vectorstore import get_or_create_table, open_store, upsert_records


class FakeModel:
    def encode(self, sentences: list[str], **kwargs: object) -> list[list[float]]:
        return [[1.0] + [0.0] * (EMBEDDING_DIM - 1) for _ in sentences]


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

    response = service.search_red_flags(query="oil smuggling", limit=MAX_SEARCH_LIMIT + 10)

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


def test_get_red_flag_returns_record_without_vector(tmp_vectors_dir):
    service = seeded_service(tmp_vectors_dir)

    response = service.get_red_flag("benefits-01")

    assert response["red_flag"]["id"] == "benefits-01"
    assert response["red_flag"]["regulatory_source"] == "FinCEN Alert FIN-2025-Alert001"
    assert "vector" not in response["red_flag"]


def test_empty_store_returns_pre_ingestion_message(tmp_vectors_dir):
    table = get_or_create_table(open_store(tmp_vectors_dir))
    service = RedFlagService(table=table, embedding_model=FakeModel())

    assert service.list_filters()["message"] == PRE_INGESTION_MESSAGE
    assert service.search_red_flags(query="anything")["results"] == []
    assert service.get_red_flag("missing")["red_flag"] is None


def test_fastmcp_tool_metadata_includes_consultation_guidance(tmp_vectors_dir):
    app = create_server(vector_dir=tmp_vectors_dir, embedding_model=FakeModel())

    tools = asyncio.run(app.list_tools())
    by_name = {tool.name: tool for tool in tools}

    assert sorted(by_name) == ["get_red_flag", "list_filters", "search_red_flags"]
    search_description = by_name["search_red_flags"].description
    assert "vague" in search_description
    assert "product/channel" in search_description
    assert "industry_types" in by_name["search_red_flags"].inputSchema["properties"]


def test_server_imports_via_mcp_dev_loader_without_sys_modules_registration():
    server_path = (
        Path(__file__).resolve().parent.parent / "src/redflag_mcp/server.py"
    )
    module_name = "mcp_dev_server_import_test"
    spec = importlib.util.spec_from_file_location(module_name, server_path)
    assert spec is not None
    assert spec.loader is not None

    sys.modules.pop(module_name, None)
    module = importlib.util.module_from_spec(spec)

    spec.loader.exec_module(module)

    assert module.mcp.name == "redflag-mcp"
