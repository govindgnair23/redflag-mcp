from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from redflag_mcp.config import VECTORS_DIR
from redflag_mcp.embeddings import EmbeddingModel, encode_query
from redflag_mcp.models import RedFlagResult
from redflag_mcp.vectorstore import (
    RedFlagFilters,
    filter_red_flags as filter_records,
    get_by_id,
    get_or_create_table,
    get_source as get_source_detail,
    list_distinct_values,
    list_sources as list_source_summaries,
    open_store,
    search,
)

MAX_SEARCH_LIMIT = 20
PRE_INGESTION_MESSAGE = (
    "No red flags are available yet. Run `uv run python scripts/ingest.py` "
    "to populate the local vector store before querying."
)

SEARCH_DESCRIPTION = """Search AML red flags using natural-language context and optional filters.

Agent guidance: if the user's request is vague, briefly ask for product/channel, industry, customer profile, geography, and transaction channel or volume before searching. If the request already names those details or has a specific scenario, search directly. Call list_filters when you need valid filter values. Use filter_red_flags for exact metadata requests; use search_red_flags for semantic relevance questions."""


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
        _add_fit_explanations(
            results,
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

    def filter_red_flags(
        self,
        *,
        limit: int = 5,
        product_types: list[str] | None = None,
        industry_types: list[str] | None = None,
        customer_profiles: list[str] | None = None,
        geographic_footprints: list[str] | None = None,
        category: str | None = None,
        risk_level: str | None = None,
        regulatory_source: str | None = None,
        source_url: str | None = None,
        source_id: str | None = None,
    ) -> dict[str, Any]:
        if self.table.count_rows() == 0:
            return {
                "message": PRE_INGESTION_MESSAGE,
                "match_type": "metadata_filter",
                "results": [],
            }
        filters = RedFlagFilters(
            product_types=product_types,
            industry_types=industry_types,
            customer_profiles=customer_profiles,
            geographic_footprints=geographic_footprints,
            category=category,
            risk_level=risk_level,
            regulatory_source=regulatory_source,
            source_url=source_url,
            source_id=source_id,
        )
        if not filters.has_any():
            return {
                "message": (
                    "Provide at least one metadata filter before using filter_red_flags."
                ),
                "match_type": "metadata_filter",
                "results": [],
            }

        clamped_limit = min(max(limit, 1), MAX_SEARCH_LIMIT)
        results = filter_records(
            self.table,
            limit=clamped_limit,
            filters=filters,
        )
        return {
            "match_type": "metadata_filter",
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

    def list_sources(self) -> dict[str, Any]:
        if self.table.count_rows() == 0:
            return {
                "message": PRE_INGESTION_MESSAGE,
                "source_count": 0,
                "sources": [],
            }

        sources = [
            source.model_dump(exclude_none=True)
            for source in list_source_summaries(self.table)
        ]
        response: dict[str, Any] = {
            "source_count": len(sources),
            "sources": sources,
        }
        return response

    def get_source(self, source_id: str) -> dict[str, Any]:
        if self.table.count_rows() == 0:
            return {"message": PRE_INGESTION_MESSAGE, "source": None}

        source = get_source_detail(self.table, source_id)
        if source is None:
            return {"message": f"Source not found: {source_id}", "source": None}
        return {"source": source.model_dump(exclude_none=True)}


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
        description=(
            "Return AML red flags for exact metadata criteria without semantic "
            "embedding search. Use this for exact metadata requests such as high-risk "
            "depository structuring red flags. Use search_red_flags instead for "
            "open-ended relevance questions."
        )
    )
    def filter_red_flags(
        limit: int = 5,
        product_types: list[str] | None = None,
        industry_types: list[str] | None = None,
        customer_profiles: list[str] | None = None,
        geographic_footprints: list[str] | None = None,
        category: str | None = None,
        risk_level: str | None = None,
        regulatory_source: str | None = None,
        source_url: str | None = None,
        source_id: str | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Filter red flags by exact stored metadata."""
        return _service_from_context(ctx).filter_red_flags(
            limit=limit,
            product_types=product_types,
            industry_types=industry_types,
            customer_profiles=customer_profiles,
            geographic_footprints=geographic_footprints,
            category=category,
            risk_level=risk_level,
            regulatory_source=regulatory_source,
            source_url=source_url,
            source_id=source_id,
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

    @mcp.tool(
        description=(
            "List ingested AML red flag source coverage with citation URLs, source "
            "counts, aggregate metadata, and red flag IDs. Use when users ask what "
            "sources or citations the corpus covers."
        )
    )
    def list_sources(ctx: Context | None = None) -> dict[str, Any]:
        """Return source coverage summaries from the ingested red flag store."""
        return _service_from_context(ctx).list_sources()

    @mcp.tool(
        description=(
            "Return bounded detail for one source by source_id, including citations, "
            "aggregate metadata, related red flag IDs, and short snippets. Use "
            "get_red_flag when full text for one red flag is needed."
        )
    )
    def get_source(source_id: str, ctx: Context | None = None) -> dict[str, Any]:
        """Return one source detail by source id."""
        return _service_from_context(ctx).get_source(source_id)


def _service_from_context(ctx: Context | None) -> RedFlagService:
    if ctx is None:
        return RedFlagService.from_vector_dir()
    state = ctx.request_context.lifespan_context
    return state.service


def _add_fit_explanations(
    results: list[RedFlagResult],
    *,
    product_types: list[str] | None = None,
    industry_types: list[str] | None = None,
    customer_profiles: list[str] | None = None,
    geographic_footprints: list[str] | None = None,
    category: str | None = None,
    risk_level: str | None = None,
) -> None:
    list_signal_specs = (
        ("Product type", "product_types", product_types),
        ("Industry type", "industry_types", industry_types),
        ("Customer profile", "customer_profiles", customer_profiles),
        ("Geographic footprint", "geographic_footprints", geographic_footprints),
    )
    for result in results:
        signals: list[str] = []
        for label, result_attr, requested in list_signal_specs:
            matches = sorted(
                set(requested or []).intersection(getattr(result, result_attr))
            )
            if matches:
                signals.append(f"{label} matches {', '.join(matches)}.")
        if category and result.category == category:
            signals.append(f"Category matches {category}.")
        elif result.category:
            signals.append(f"Category is {result.category}.")
        if risk_level and result.risk_level == risk_level:
            signals.append(f"Risk level matches {risk_level}.")
        elif result.risk_level:
            signals.append(f"Risk level is {result.risk_level}.")
        if result.regulatory_source:
            signals.append(f"Source is {result.regulatory_source}.")
        if not signals:
            signals.append("Semantic match to the query context.")
        result.fit_signals = signals
        result.fit_explanation = " ".join(signals[:3])
