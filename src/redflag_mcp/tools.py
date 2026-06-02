from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, TypeAlias

from mcp.server.fastmcp import Context, FastMCP
from pydantic import Field

from redflag_mcp.config import (
    CATEGORIES,
    CUSTOMER_PROFILES,
    INDUSTRY_GROUPS,
    INDUSTRY_TYPES,
    PRODUCT_TYPES,
    REGULATOR_JURISDICTIONS,
    REGULATORS,
    RISK_LEVELS,
    SUBJECTS,
    TRANSACTION_PATTERNS,
    TYPOLOGY_FAMILIES,
    VECTORS_DIR,
)
from redflag_mcp.embeddings import EmbeddingModel, encode_query
from redflag_mcp.lexicalstore import LexicalRedFlagFilters, LexicalStore
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
MAX_QUERY_LENGTH = 1000
MAX_FILTER_VALUES = 25
ROUTE_NEEDS_MORE_CONTEXT = "needs_more_context"
ROUTE_METADATA_FILTER = "metadata_filter"
ROUTE_FILTERED_SEMANTIC_SEARCH = "filtered_semantic_search"
ROUTE_DIRECT_SEMANTIC_SEARCH = "direct_semantic_search"
PRIMARY_FILTER_FIELDS = (
    "product_types",
    "industry_types",
    "customer_profiles",
    "geographic_footprints",
    "category",
    "risk_level",
)
CONTEXT_FILTER_FIELDS = (
    "product_types",
    "industry_types",
    "customer_profiles",
    "geographic_footprints",
)
QUERY_STOPWORDS = {
    "a",
    "an",
    "and",
    "apply",
    "applicable",
    "are",
    "flag",
    "flags",
    "for",
    "i",
    "my",
    "of",
    "product",
    "products",
    "red",
    "risk",
    "risks",
    "should",
    "the",
    "to",
    "what",
    "which",
}
SCENARIO_TERMS = {
    "ach",
    "cash",
    "customers",
    "frequent",
    "importers",
    "invoice",
    "invoices",
    "laredo",
    "moving",
    "payments",
    "third-party",
    "transaction",
    "transactions",
    "unusual",
    "wires",
}
PRE_INGESTION_MESSAGE = (
    "No red flags are available yet. Run `uv run python scripts/ingest.py` "
    "to populate the local vector store before querying."
)

def _string_enum_schema(values: set[str] | frozenset[str]) -> dict[str, object]:
    return {"enum": sorted(values)}


def _list_enum_schema(values: set[str] | frozenset[str]) -> dict[str, object]:
    return {"items": {"type": "string", "enum": sorted(values)}}


CategoryValue: TypeAlias = Annotated[
    str,
    Field(json_schema_extra=_string_enum_schema(CATEGORIES)),
]
CustomerProfilesValue: TypeAlias = Annotated[
    list[str],
    Field(json_schema_extra=_list_enum_schema(CUSTOMER_PROFILES)),
]
IndustryGroupsValue: TypeAlias = Annotated[
    list[str],
    Field(json_schema_extra=_list_enum_schema(INDUSTRY_GROUPS)),
]
IndustryTypesValue: TypeAlias = Annotated[
    list[str],
    Field(json_schema_extra=_list_enum_schema(INDUSTRY_TYPES)),
]
ProductTypesValue: TypeAlias = Annotated[
    list[str],
    Field(json_schema_extra=_list_enum_schema(PRODUCT_TYPES)),
]
RegulatorJurisdictionValue: TypeAlias = Annotated[
    str,
    Field(json_schema_extra=_string_enum_schema(frozenset(REGULATOR_JURISDICTIONS.values()))),
]
RegulatorValue: TypeAlias = Annotated[
    str,
    Field(json_schema_extra=_string_enum_schema(REGULATORS)),
]
RiskLevelValue: TypeAlias = Annotated[
    str,
    Field(json_schema_extra=_string_enum_schema(RISK_LEVELS)),
]
SubjectsValue: TypeAlias = Annotated[
    list[str],
    Field(json_schema_extra=_list_enum_schema(SUBJECTS)),
]
TransactionPatternsValue: TypeAlias = Annotated[
    list[str],
    Field(json_schema_extra=_list_enum_schema(TRANSACTION_PATTERNS)),
]
TypologyFamiliesValue: TypeAlias = Annotated[
    list[str],
    Field(json_schema_extra=_list_enum_schema(TYPOLOGY_FAMILIES)),
]

SEARCH_DESCRIPTION = """Search AML red flags using natural-language context and optional filters.

Agent guidance: use classify_red_flag_request before searching for ambiguous "what red flags apply" requests. If the user's request is vague, briefly ask for product/channel, industry, customer profile, geography, and transaction channel or volume before searching. If the request already names those details or has a specific scenario, search directly. Call list_filters when you need valid filter values. Use filter_red_flags for exact metadata requests and exhaustive enumeration; use search_red_flags for ranked relevance questions. For broad investigative topics such as human trafficking red flags, use subjects as an eligibility filter. For broad sector requests such as trade logistics red flags, use industry_groups as an eligibility filter. For country or jurisdiction requests, translate names to regulator_jurisdiction codes before filtering, such as France -> FR, Singapore -> SG, Australia -> AU, United Kingdom/UK -> GB, United States/US -> US, and European Union/EU regulators -> EU."""


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

    @classmethod
    def from_corpus_path(
        cls,
        corpus_path: Path,
        embedding_model: EmbeddingModel | None = None,
    ) -> RedFlagService:
        return cls(
            table=LexicalStore.open(corpus_path),
            embedding_model=embedding_model,
        )

    def search_red_flags(
        self,
        *,
        query: str,
        limit: int = 5,
        product_types: list[str] | None = None,
        industry_types: list[str] | None = None,
        industry_groups: list[str] | None = None,
        customer_profiles: list[str] | None = None,
        geographic_footprints: list[str] | None = None,
        subjects: list[str] | None = None,
        category: str | None = None,
        risk_level: str | None = None,
        regulator_jurisdiction: str | None = None,
    ) -> dict[str, Any]:
        validation_error = _validate_public_search_inputs(
            query=query,
            product_types=product_types,
            industry_types=industry_types,
            industry_groups=industry_groups,
            customer_profiles=customer_profiles,
            geographic_footprints=geographic_footprints,
            subjects=subjects,
        )
        if validation_error is not None:
            return {"message": validation_error, "results": []}

        if self.table.count_rows() == 0:
            return self._with_corpus({"message": PRE_INGESTION_MESSAGE, "results": []})

        clamped_limit = min(max(limit, 1), MAX_SEARCH_LIMIT)
        if self._is_corpus_mode():
            results = self.table.search(
                query,
                limit=clamped_limit,
                product_types=product_types,
                industry_types=industry_types,
                industry_groups=industry_groups,
                customer_profiles=customer_profiles,
                geographic_footprints=geographic_footprints,
                subjects=subjects,
                category=category,
                risk_level=risk_level,
                regulator_jurisdiction=regulator_jurisdiction,
            )
            return self._with_corpus(
                {
                    "query": query,
                    "limit": clamped_limit,
                    "requested_limit": limit,
                    "applied_limit": clamped_limit,
                    "returned": len(results),
                    "truncated": len(results) >= clamped_limit,
                    "results": [
                        result.model_dump(exclude_none=True) for result in results
                    ],
                }
            )

        query_vector = encode_query(query, model=self.embedding_model)
        results = search(
            self.table,
            query_vector,
            limit=clamped_limit,
            product_types=product_types,
            industry_types=industry_types,
            industry_groups=industry_groups,
            customer_profiles=customer_profiles,
            geographic_footprints=geographic_footprints,
            subjects=subjects,
            category=category,
            risk_level=risk_level,
            regulator_jurisdiction=regulator_jurisdiction,
        )
        _add_fit_explanations(
            results,
            product_types=product_types,
            industry_types=industry_types,
            customer_profiles=customer_profiles,
            geographic_footprints=geographic_footprints,
            category=category,
            risk_level=risk_level,
            regulator_jurisdiction=regulator_jurisdiction,
        )
        return self._with_corpus(
            {
                "query": query,
                "limit": clamped_limit,
                "requested_limit": limit,
                "applied_limit": clamped_limit,
                "returned": len(results),
                "truncated": len(results) >= clamped_limit,
                "results": [result.model_dump(exclude_none=True) for result in results],
            }
        )

    def filter_red_flags(
        self,
        *,
        limit: int = 5,
        cursor: str | None = None,
        product_types: list[str] | None = None,
        industry_types: list[str] | None = None,
        industry_groups: list[str] | None = None,
        customer_profiles: list[str] | None = None,
        geographic_footprints: list[str] | None = None,
        typology_family: list[str] | None = None,
        transaction_patterns: list[str] | None = None,
        subjects: list[str] | None = None,
        category: str | None = None,
        risk_level: str | None = None,
        regulator: str | None = None,
        regulator_jurisdiction: str | None = None,
        issued_after: str | None = None,
        issued_before: str | None = None,
        regulatory_source: str | None = None,
        source_url: str | None = None,
        source_id: str | None = None,
    ) -> dict[str, Any]:
        validation_error = _validate_filter_cardinality(
            product_types=product_types,
            industry_types=industry_types,
            industry_groups=industry_groups,
            customer_profiles=customer_profiles,
            geographic_footprints=geographic_footprints,
            typology_family=typology_family,
            transaction_patterns=transaction_patterns,
            subjects=subjects,
        )
        if validation_error is None:
            validation_error = _validate_known_filter_values(
                product_types=product_types,
                industry_types=industry_types,
                industry_groups=industry_groups,
                customer_profiles=customer_profiles,
                typology_family=typology_family,
                transaction_patterns=transaction_patterns,
                subjects=subjects,
            )
        if validation_error is not None:
            return {
                "message": validation_error,
                "match_type": "metadata_filter",
                "results": [],
            }

        if self.table.count_rows() == 0:
            return self._with_corpus(
                {
                    "message": PRE_INGESTION_MESSAGE,
                    "match_type": "metadata_filter",
                    "results": [],
                }
            )
        filters = (
            LexicalRedFlagFilters(
                product_types=product_types,
                industry_types=industry_types,
                industry_groups=industry_groups,
                customer_profiles=customer_profiles,
                geographic_footprints=geographic_footprints,
                typology_family=typology_family,
                transaction_patterns=transaction_patterns,
                subjects=subjects,
                category=category,
                risk_level=risk_level,
                regulator=regulator,
                regulator_jurisdiction=regulator_jurisdiction,
                issued_after=issued_after,
                issued_before=issued_before,
                regulatory_source=regulatory_source,
                source_url=source_url,
                source_id=source_id,
            )
            if self._is_corpus_mode()
            else RedFlagFilters(
                product_types=product_types,
                industry_types=industry_types,
                industry_groups=industry_groups,
                customer_profiles=customer_profiles,
                geographic_footprints=geographic_footprints,
                typology_family=typology_family,
                transaction_patterns=transaction_patterns,
                subjects=subjects,
                category=category,
                risk_level=risk_level,
                regulator=regulator,
                regulator_jurisdiction=regulator_jurisdiction,
                issued_after=issued_after,
                issued_before=issued_before,
                regulatory_source=regulatory_source,
                source_url=source_url,
                source_id=source_id,
            )
        )
        if not filters.has_any():
            return self._with_corpus(
                {
                    "message": (
                        "Provide at least one metadata filter before using "
                        "filter_red_flags."
                    ),
                    "match_type": "metadata_filter",
                    "results": [],
                }
            )

        clamped_limit = min(max(limit, 1), MAX_SEARCH_LIMIT)
        cursor_offset, cursor_error = _decode_cursor(cursor)
        if cursor_error is not None:
            return self._with_corpus(
                {
                    "message": cursor_error,
                    "match_type": "metadata_filter",
                    "limit": clamped_limit,
                    "requested_limit": limit,
                    "applied_limit": clamped_limit,
                    "returned": 0,
                    "total_matched": 0,
                    "truncated": False,
                    "next_cursor": None,
                    "results": [],
                }
            )

        total_rows = self.table.count_rows()
        if isinstance(self.table, LexicalStore):
            assert isinstance(filters, LexicalRedFlagFilters)
            all_results = self.table.filter_red_flags(limit=total_rows, filters=filters)
        else:
            assert isinstance(filters, RedFlagFilters)
            all_results = filter_records(
                self.table,
                limit=total_rows,
                filters=filters,
            )
        total_matched = len(all_results)
        page_results = all_results[cursor_offset : cursor_offset + clamped_limit]
        next_offset = cursor_offset + len(page_results)
        next_cursor = (
            _encode_cursor(next_offset) if next_offset < total_matched else None
        )
        return self._with_corpus(
            {
                "match_type": "metadata_filter",
                "limit": clamped_limit,
                "requested_limit": limit,
                "applied_limit": clamped_limit,
                "returned": len(page_results),
                "total_matched": total_matched,
                "truncated": next_cursor is not None,
                "next_cursor": next_cursor,
                "results": [
                    result.model_dump(exclude_none=True) for result in page_results
                ],
            }
        )

    def get_red_flag(self, red_flag_id: str) -> dict[str, Any]:
        if self.table.count_rows() == 0:
            return self._with_corpus(
                {"message": PRE_INGESTION_MESSAGE, "red_flag": None}
            )

        result = (
            self.table.get_by_id(red_flag_id)
            if self._is_corpus_mode()
            else get_by_id(self.table, red_flag_id)
        )
        if result is None:
            return self._with_corpus(
                {"message": f"Red flag not found: {red_flag_id}", "red_flag": None}
            )
        return self._with_corpus({"red_flag": result.model_dump(exclude_none=True)})

    def list_filters(self) -> dict[str, Any]:
        filters = (
            self.table.list_distinct_values()
            if self._is_corpus_mode()
            else list_distinct_values(self.table)
        )
        filters["subjects"] = sorted(SUBJECTS)
        filters["industry_groups"] = sorted(INDUSTRY_GROUPS)
        if self.table.count_rows() == 0:
            return self._with_corpus(
                {"message": PRE_INGESTION_MESSAGE, "filters": filters}
            )
        return self._with_corpus({"filters": filters})

    def classify_red_flag_request(
        self,
        *,
        query: str,
        limit: int = 5,
        product_types: list[str] | None = None,
        industry_types: list[str] | None = None,
        industry_groups: list[str] | None = None,
        customer_profiles: list[str] | None = None,
        geographic_footprints: list[str] | None = None,
        subjects: list[str] | None = None,
        category: str | None = None,
        risk_level: str | None = None,
    ) -> dict[str, Any]:
        clamped_limit = min(max(limit, 1), MAX_SEARCH_LIMIT)
        filters = _clean_filter_arguments(
            product_types=product_types,
            industry_types=industry_types,
            industry_groups=industry_groups,
            customer_profiles=customer_profiles,
            geographic_footprints=geographic_footprints,
            subjects=subjects,
            category=category,
            risk_level=risk_level,
        )
        missing_context = [
            field_name
            for field_name in CONTEXT_FILTER_FIELDS
            if field_name not in filters
        ]
        enough_filters = _has_enough_context_filters(filters)
        rich_narrative = _has_rich_narrative(query)

        if enough_filters and rich_narrative:
            route = ROUTE_FILTERED_SEMANTIC_SEARCH
            recommended_tool = "search_red_flags"
            recommended_arguments = {"query": query, "limit": clamped_limit, **filters}
            follow_up_question = None
            reason = (
                "The request includes usable metadata filters and a specific "
                "scenario for semantic ranking."
            )
        elif enough_filters:
            route = ROUTE_METADATA_FILTER
            recommended_tool = "filter_red_flags"
            recommended_arguments = {"limit": clamped_limit, **filters}
            follow_up_question = None
            reason = (
                "The request includes enough structured metadata and no rich "
                "scenario requiring semantic ranking."
            )
        elif rich_narrative:
            route = ROUTE_DIRECT_SEMANTIC_SEARCH
            recommended_tool = "search_red_flags"
            recommended_arguments = {"query": query, "limit": clamped_limit, **filters}
            follow_up_question = None
            reason = (
                "The request lacks enough metadata filters but has enough "
                "narrative detail for direct semantic search."
            )
        else:
            route = ROUTE_NEEDS_MORE_CONTEXT
            recommended_tool = None
            recommended_arguments = {}
            follow_up_question = (
                "What product/channel, industry, customer profile, geography, "
                "or transaction pattern should the red flags focus on?"
            )
            reason = (
                "The request lacks enough structured metadata and is too vague "
                "for useful semantic ranking."
            )

        return {
            "route": route,
            "confidence": "high",
            "reason": reason,
            "inferred_filters": filters,
            "missing_context": missing_context,
            "recommended_tool": recommended_tool,
            "recommended_arguments": recommended_arguments,
            "follow_up_question": follow_up_question,
        }

    def list_sources(self) -> dict[str, Any]:
        if self.table.count_rows() == 0:
            return self._with_corpus(
                {
                    "message": PRE_INGESTION_MESSAGE,
                    "source_count": 0,
                    "sources": [],
                }
            )

        sources = [
            source.model_dump(exclude_none=True)
            for source in (
                self.table.list_sources()
                if self._is_corpus_mode()
                else list_source_summaries(self.table)
            )
        ]
        response: dict[str, Any] = {
            "source_count": len(sources),
            "sources": sources,
        }
        return self._with_corpus(response)

    def get_source(self, source_id: str) -> dict[str, Any]:
        if self.table.count_rows() == 0:
            return self._with_corpus(
                {"message": PRE_INGESTION_MESSAGE, "source": None}
            )

        source = (
            self.table.get_source(source_id)
            if self._is_corpus_mode()
            else get_source_detail(self.table, source_id)
        )
        if source is None:
            return self._with_corpus(
                {"message": f"Source not found: {source_id}", "source": None}
            )
        return self._with_corpus({"source": source.model_dump(exclude_none=True)})

    def _is_corpus_mode(self) -> bool:
        return isinstance(self.table, LexicalStore)

    def _with_corpus(self, response: dict[str, Any]) -> dict[str, Any]:
        if self._is_corpus_mode():
            response = dict(response)
            response["corpus"] = self.table.corpus.model_dump(exclude_none=True)
        return response


def register_tools(mcp: FastMCP) -> None:
    @mcp.tool(
        description=(
            "Classify an AML red flag request before searching when the user asks "
            "which red flags apply to a product, customer, geography, industry, "
            "scenario, transaction pattern, or institution profile. Returns one "
            "route: needs_more_context, metadata_filter, filtered_semantic_search, "
            "or direct_semantic_search, plus the recommended next tool and arguments."
        )
    )
    def classify_red_flag_request(
        query: str,
        limit: int = 5,
        product_types: ProductTypesValue | None = None,
        industry_types: IndustryTypesValue | None = None,
        industry_groups: IndustryGroupsValue | None = None,
        customer_profiles: CustomerProfilesValue | None = None,
        geographic_footprints: list[str] | None = None,
        subjects: SubjectsValue | None = None,
        category: CategoryValue | None = None,
        risk_level: RiskLevelValue | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Return routing guidance for an AML red flag request."""
        return _service_from_context(ctx).classify_red_flag_request(
            query=query,
            limit=limit,
            product_types=product_types,
            industry_types=industry_types,
            industry_groups=industry_groups,
            customer_profiles=customer_profiles,
            geographic_footprints=geographic_footprints,
            subjects=subjects,
            category=category,
            risk_level=risk_level,
        )

    @mcp.tool(description=SEARCH_DESCRIPTION)
    def search_red_flags(
        query: str,
        limit: int = 5,
        product_types: ProductTypesValue | None = None,
        industry_types: IndustryTypesValue | None = None,
        industry_groups: IndustryGroupsValue | None = None,
        customer_profiles: CustomerProfilesValue | None = None,
        geographic_footprints: list[str] | None = None,
        subjects: SubjectsValue | None = None,
        category: CategoryValue | None = None,
        risk_level: RiskLevelValue | None = None,
        regulator_jurisdiction: RegulatorJurisdictionValue | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Search for relevant AML red flags and return sourced results."""
        return _service_from_context(ctx).search_red_flags(
            query=query,
            limit=limit,
            product_types=product_types,
            industry_types=industry_types,
            industry_groups=industry_groups,
            customer_profiles=customer_profiles,
            geographic_footprints=geographic_footprints,
            subjects=subjects,
            category=category,
            risk_level=risk_level,
            regulator_jurisdiction=regulator_jurisdiction,
        )

    @mcp.tool(
        description=(
            "Return AML red flags for exact metadata criteria without semantic "
            "embedding search. Use this for exact metadata requests, broad "
            "investigative subjects, and broad industry groups, such as high-risk "
            "depository structuring red flags, FINTRAC human trafficking red flags "
            "with subjects, trade logistics red flags with industry_groups, or red "
            "flags from regulators in France. Paginate with next_cursor whenever "
            "truncated is true. "
            "For country or jurisdiction requests, translate names to ISO-style "
            "regulator_jurisdiction codes before filtering: France -> FR, Singapore "
            "-> SG, Australia -> AU, United Kingdom/UK -> GB, United States/US -> "
            "US, and European Union/EU regulators -> EU. Prefer "
            "filter_red_flags(regulator_jurisdiction=\"FR\") for requests like "
            "\"red flags from regulators in France.\" Use search_red_flags instead "
            "for open-ended relevance questions."
        )
    )
    def filter_red_flags(
        limit: int = 5,
        cursor: str | None = None,
        product_types: ProductTypesValue | None = None,
        industry_types: IndustryTypesValue | None = None,
        industry_groups: IndustryGroupsValue | None = None,
        customer_profiles: CustomerProfilesValue | None = None,
        geographic_footprints: list[str] | None = None,
        typology_family: TypologyFamiliesValue | None = None,
        transaction_patterns: TransactionPatternsValue | None = None,
        subjects: SubjectsValue | None = None,
        category: CategoryValue | None = None,
        risk_level: RiskLevelValue | None = None,
        regulator: RegulatorValue | None = None,
        regulator_jurisdiction: RegulatorJurisdictionValue | None = None,
        issued_after: str | None = None,
        issued_before: str | None = None,
        regulatory_source: str | None = None,
        source_url: str | None = None,
        source_id: str | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Filter red flags by exact stored metadata."""
        return _service_from_context(ctx).filter_red_flags(
            limit=limit,
            cursor=cursor,
            product_types=product_types,
            industry_types=industry_types,
            industry_groups=industry_groups,
            customer_profiles=customer_profiles,
            geographic_footprints=geographic_footprints,
            typology_family=typology_family,
            transaction_patterns=transaction_patterns,
            subjects=subjects,
            category=category,
            risk_level=risk_level,
            regulator=regulator,
            regulator_jurisdiction=regulator_jurisdiction,
            issued_after=issued_after,
            issued_before=issued_before,
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
            "customer_profiles, geographic_footprints, typology_family, "
            "transaction_patterns, category, risk_level, regulator, and "
            "regulator_jurisdiction. Agents should call this before or during "
            "consultation when they need valid local filter values, especially "
            "when unsure which regulator_jurisdiction codes are available."
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
    if state.service is None:
        raise RuntimeError(state.readiness.message)
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
    regulator_jurisdiction: str | None = None,
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
        if (
            regulator_jurisdiction
            and result.regulator_jurisdiction == regulator_jurisdiction
        ):
            signals.append(f"Regulator jurisdiction matches {regulator_jurisdiction}.")
        elif result.regulator_jurisdiction:
            signals.append(f"Regulator jurisdiction is {result.regulator_jurisdiction}.")
        if result.regulatory_source:
            signals.append(f"Source is {result.regulatory_source}.")
        if result.regulator:
            signals.append(f"Regulator is {result.regulator}.")
        if not signals:
            signals.append("Semantic match to the query context.")
        result.fit_signals = signals
        result.fit_explanation = " ".join(signals[:3])


def _clean_filter_arguments(**filters: object) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for field_name, value in filters.items():
        if isinstance(value, list):
            values = [item for item in value if item]
            if values:
                cleaned[field_name] = values
        elif value:
            cleaned[field_name] = value
    return cleaned


def _validate_public_search_inputs(
    *,
    query: str,
    product_types: list[str] | None = None,
    industry_types: list[str] | None = None,
    industry_groups: list[str] | None = None,
    customer_profiles: list[str] | None = None,
    geographic_footprints: list[str] | None = None,
    subjects: list[str] | None = None,
) -> str | None:
    if len(query) > MAX_QUERY_LENGTH:
        return f"Search query is too long; maximum length is {MAX_QUERY_LENGTH} characters."

    cardinality_error = _validate_filter_cardinality(
        product_types=product_types,
        industry_types=industry_types,
        industry_groups=industry_groups,
        customer_profiles=customer_profiles,
        geographic_footprints=geographic_footprints,
        subjects=subjects,
    )
    if cardinality_error is not None:
        return cardinality_error
    return _validate_known_filter_values(
        product_types=product_types,
        industry_types=industry_types,
        industry_groups=industry_groups,
        customer_profiles=customer_profiles,
        subjects=subjects,
    )


def _validate_filter_cardinality(**filters: list[str] | None) -> str | None:
    filter_values = sum(len(value or []) for value in filters.values())
    if filter_values > MAX_FILTER_VALUES:
        return (
            "Request has too many filter values; maximum total filter "
            f"values is {MAX_FILTER_VALUES}."
        )
    return None


def _validate_known_filter_values(**filters: list[str] | None) -> str | None:
    vocabularies = {
        "product_types": PRODUCT_TYPES,
        "industry_types": INDUSTRY_TYPES,
        "industry_groups": INDUSTRY_GROUPS,
        "customer_profiles": CUSTOMER_PROFILES,
        "typology_family": TYPOLOGY_FAMILIES,
        "transaction_patterns": TRANSACTION_PATTERNS,
        "subjects": SUBJECTS,
    }
    for field_name, values in filters.items():
        valid_values = vocabularies[field_name]
        unknown = sorted(set(values or []) - set(valid_values))
        if unknown:
            return (
                f"Unknown {field_name} value(s): {', '.join(unknown)}. "
                "Call list_filters for valid values."
            )
    return None


def _encode_cursor(offset: int) -> str:
    payload = json.dumps({"offset": offset}, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii")


def _decode_cursor(cursor: str | None) -> tuple[int, str | None]:
    if cursor is None:
        return 0, None
    try:
        decoded = base64.urlsafe_b64decode(cursor.encode("ascii"))
        payload = json.loads(decoded.decode("utf-8"))
    except (binascii.Error, json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return 0, "Invalid cursor. Use the next_cursor value from the previous page."
    offset = payload.get("offset") if isinstance(payload, dict) else None
    if not isinstance(offset, int) or offset < 0:
        return 0, "Invalid cursor. Use the next_cursor value from the previous page."
    return offset, None


def _has_enough_context_filters(filters: dict[str, Any]) -> bool:
    if filters.get("subjects") or filters.get("industry_groups"):
        return True
    return sum(1 for field_name in PRIMARY_FILTER_FIELDS if filters.get(field_name)) >= 2


def _has_rich_narrative(query: str) -> bool:
    terms = [
        term
        for term in re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)?", query.lower())
        if term not in QUERY_STOPWORDS
    ]
    if len(terms) >= 7:
        return True
    return len(terms) >= 5 and len(set(terms).intersection(SCENARIO_TERMS)) >= 2
