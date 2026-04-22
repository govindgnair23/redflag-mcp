from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from redflag_mcp.config import VECTORS_DIR
from redflag_mcp.embeddings import EmbeddingModel, encode_query
from redflag_mcp.vectorstore import (
    get_by_id,
    get_or_create_table,
    list_distinct_values,
    open_store,
    search,
)

MAX_SEARCH_LIMIT = 20
PRE_INGESTION_MESSAGE = (
    "No red flags are available yet. Run `uv run python scripts/ingest.py` "
    "to populate the local vector store before querying."
)

SEARCH_DESCRIPTION = """Search AML red flags using natural-language context and optional filters.

Agent guidance: if the user's request is vague, briefly ask for product/channel, industry, customer profile, geography, and transaction channel or volume before searching. If the request already includes enough context, search directly. Call list_filters when you need the available filter values."""


@dataclass
class RedFlagService:
    table: Any
    embedding_model: EmbeddingModel | None = None

    @classmethod
    def from_vector_dir(
        cls,
        vector_dir: Path = VECTORS_DIR,
        embedding_model: EmbeddingModel | None = None,
    ) -> RedFlagService:
        table = get_or_create_table(open_store(vector_dir))
        return cls(table=table, embedding_model=embedding_model)

    def search_red_flags(
        self,
        *,
        query: str,
        limit: int = 5,
        product_types: list[str] | None = None,
        industry_types: list[str] | None = None,
        customer_profiles: list[str] | None = None,
        geographic_footprints: list[str] | None = None,
        category: str | None = None,
        risk_level: str | None = None,
    ) -> dict[str, Any]:
        if self.table.count_rows() == 0:
            return {"message": PRE_INGESTION_MESSAGE, "results": []}

        clamped_limit = min(max(limit, 1), MAX_SEARCH_LIMIT)
        query_vector = encode_query(query, model=self.embedding_model)
        results = search(
            self.table,
            query_vector,
            limit=clamped_limit,
            product_types=product_types,
            industry_types=industry_types,
            customer_profiles=customer_profiles,
            geographic_footprints=geographic_footprints,
            category=category,
            risk_level=risk_level,
        )
        return {
            "query": query,
            "limit": clamped_limit,
            "results": [result.model_dump(exclude_none=True) for result in results],
        }

    def get_red_flag(self, red_flag_id: str) -> dict[str, Any]:
        if self.table.count_rows() == 0:
            return {"message": PRE_INGESTION_MESSAGE, "red_flag": None}

        result = get_by_id(self.table, red_flag_id)
        if result is None:
            return {"message": f"Red flag not found: {red_flag_id}", "red_flag": None}
        return {"red_flag": result.model_dump(exclude_none=True)}

    def list_filters(self) -> dict[str, Any]:
        filters = list_distinct_values(self.table)
        if self.table.count_rows() == 0:
            return {"message": PRE_INGESTION_MESSAGE, "filters": filters}
        return {"filters": filters}


def register_tools(mcp: FastMCP) -> None:
    @mcp.tool(description=SEARCH_DESCRIPTION)
    def search_red_flags(
        query: str,
        limit: int = 5,
        product_types: list[str] | None = None,
        industry_types: list[str] | None = None,
        customer_profiles: list[str] | None = None,
        geographic_footprints: list[str] | None = None,
        category: str | None = None,
        risk_level: str | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Search for relevant AML red flags and return sourced results."""
        return _service_from_context(ctx).search_red_flags(
            query=query,
            limit=limit,
            product_types=product_types,
            industry_types=industry_types,
            customer_profiles=customer_profiles,
            geographic_footprints=geographic_footprints,
            category=category,
            risk_level=risk_level,
        )

    @mcp.tool(
        description="Return one AML red flag by id, including source and citation metadata."
    )
    def get_red_flag(red_flag_id: str, ctx: Context | None = None) -> dict[str, Any]:
        """Return one red flag by id."""
        return _service_from_context(ctx).get_red_flag(red_flag_id)

    @mcp.tool(
        description=(
            "List available filter values for product_types, industry_types, "
            "customer_profiles, geographic_footprints, category, and risk_level. "
            "Agents should call this before or during consultation when they need "
            "valid local filter values."
        )
    )
    def list_filters(ctx: Context | None = None) -> dict[str, Any]:
        """Return distinct filter values from the local red flag store."""
        return _service_from_context(ctx).list_filters()


def _service_from_context(ctx: Context | None) -> RedFlagService:
    if ctx is None:
        return RedFlagService.from_vector_dir()
    state = ctx.request_context.lifespan_context
    return state.service
