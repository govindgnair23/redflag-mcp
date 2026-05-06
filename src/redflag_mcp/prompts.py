from __future__ import annotations

from mcp.server.fastmcp import FastMCP


CONSULT_AML_RED_FLAGS_PROMPT = """Guide an analyst through AML red flag retrieval.

Use classify_red_flag_request before retrieval when the user's request mixes product, customer, geography, industry, scenario, transaction pattern, or institution-profile context. It returns one of four routes:
- needs_more_context: ask one brief follow-up through normal chat unless richer client elicitation is available.
- metadata_filter: call filter_red_flags because supplied metadata is enough and no rich narrative needs semantic ranking.
- filtered_semantic_search: call search_red_flags with filters because supplied metadata defines eligibility and the rich narrative should rank matching records.
- direct_semantic_search: call search_red_flags only when metadata is insufficient but the user gave a rich narrative.

If the user's question is vague, ask one brief follow-up that covers product/channel, industry, customer profile, geography, and transaction channel or volume. If the user already provided those details or described a specific scenario, do not add consultation friction.

Use list_filters when you need valid local metadata values. Use filter_red_flags for exact metadata requests, such as records matching product_types, category, risk_level, regulator_jurisdiction, customer_profiles, geographic_footprints, industry_types, source_id, source_url, or regulatory_source. Translate country or jurisdiction names to canonical regulator_jurisdiction codes before filtering: France -> FR, Singapore -> SG, Australia -> AU, United Kingdom/UK -> GB, United States/US -> US, and European Union/EU regulators -> EU. Prefer filter_red_flags(regulator_jurisdiction="FR") for requests like "red flags from regulators in France." Use search_red_flags for semantic relevance questions. Use list_sources and get_source when the user asks what sources or citations are represented, and use get_red_flag when full text for one result is needed.

When presenting results, keep fit explanations bounded to the returned metadata, scores, citations, and fit_signals. Do not claim legal applicability or regulatory obligation beyond the retrieved source context."""


def register_prompts(mcp: FastMCP) -> None:
    @mcp.prompt(
        name="consult_aml_red_flags",
        description=(
            "Conduct a follow-up-first AML red flag retrieval workflow and route "
            "exact metadata versus semantic search requests."
        ),
    )
    def consult_aml_red_flags() -> str:
        """Return hosted-client guidance for AML red flag retrieval."""
        return CONSULT_AML_RED_FLAGS_PROMPT
