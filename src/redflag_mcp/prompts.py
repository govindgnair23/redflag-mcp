from __future__ import annotations

from mcp.server.fastmcp import FastMCP


CONSULT_AML_RED_FLAGS_PROMPT = """Guide an analyst through AML red flag retrieval.

If the user's question is vague, ask one brief follow-up that covers product/channel, industry, customer profile, geography, and transaction channel or volume. If the user already provided those details or described a specific scenario, do not add consultation friction.

Use list_filters when you need valid local metadata values. Use filter_red_flags for exact metadata requests, such as records matching product_types, category, risk_level, customer_profiles, geographic_footprints, industry_types, source_id, source_url, or regulatory_source. Use search_red_flags for semantic relevance questions. Use list_sources and get_source when the user asks what sources or citations are represented, and use get_red_flag when full text for one result is needed.

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
