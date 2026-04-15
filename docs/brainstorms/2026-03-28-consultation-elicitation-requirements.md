---
date: 2026-03-28
topic: consultation-elicitation
---

# AML Red Flag Consultation Elicitation

## Problem Frame

When a BSA officer asks "what red flags apply to my crypto product?", the query is too vague for semantic search to return precise, relevant results. "Crypto" encompasses retail exchanges, ATMs, DeFi protocols, institutional custody services, and more — each with different risk profiles, customer bases, and expected transaction patterns. Directly embedding an underspecified query produces generic results that a compliance officer has to manually filter. The fix is to instruct the AI agent to conduct a brief consultation before searching — asking the right clarifying questions to build a specific, contextually rich search query.

## Requirements

- R1. The `search_red_flags` tool docstring includes a consultation protocol: when the incoming query lacks product specifics, the agent is instructed to conduct a consultation before calling the tool.
- R2. The consultation covers five dimensions: (1) product sub-type, (2) **industry type** (e.g., depository institution, casino, MSB, securities broker-dealer, insurance, investment advisor, real estate), (3) customer profile, (4) geographic footprint, and (5) transaction channels and volumes. The agent uses its own AML domain knowledge to ask appropriate questions for the stated product and industry.
- R3. The consultation is conditional: the agent assesses query specificity before triggering it. A detailed query (e.g., "retail crypto exchange serving US customers with ACH on-ramps") skips the consultation and searches directly.
- R4. After the consultation, the agent synthesizes the answers into both an enriched natural-language query and structured filter values for `search_red_flags`. Because customer profiles and geographic footprints are now stored metadata fields (multi-value lists), the agent can pass them as filters — not just fold them into query text — improving precision beyond what semantic search alone provides.
- R5. The feature requires no new MCP server tools, no server-side LLM calls, and no conversation state — the consultation protocol is entirely defined in the `search_red_flags` tool docstring.

## Success Criteria

- A BSA officer saying "what red flags apply to my crypto product?" is asked clarifying questions and receives results meaningfully more specific than a direct embedding of that query would produce.
- A BSA officer saying "what FinCEN red flags apply to retail crypto exchanges serving US customers via ACH?" receives results directly — no consultation triggered.
- Agents using different LLMs (Claude, GPT) produce equivalent consultation behavior, because the protocol is defined in the tool interface, not in a platform-specific system prompt.
- The `list_filters` tool docstring is updated to recommend calling it early — before or during the consultation — so the agent can reference valid values for all five filterable dimensions: `product_types`, `industry_types`, `customer_profiles`, `geographic_footprints`, and `categories`.

## Scope Boundaries

- No new MCP server tools or endpoints (beyond the data model change noted in Dependencies)
- No server-side question generation, LLM calls, or sampling for the consultation
- No conversation history, session state, or multi-turn tracking between tool calls
- No consultation config file or admin UI for managing question sets
- The agent's own domain knowledge supplies the consultation questions — the server does not prescribe exact question wording
- Adding `industry_types` to the data model is a prerequisite, not a feature of the consultation itself — it is a minor extension to the base plan

## Key Decisions

- **Agent-orchestrated over MCP elicitation protocol**: MCP's `elicitation/create` capability is not universally supported across clients. The server must work with any agentic interface, so the consultation must be driven by the agent, not the server.
- **Tool docstring as the delivery mechanism**: The agent reads tool docstrings to understand how to use a tool. Encoding the consultation protocol in the docstring ensures the behavior travels with the tool definition, regardless of which AI agent or system prompt is in use.
- **Conditional trigger**: Always prompting consultation adds friction for users with specific queries. The agent should use judgment — vague product references trigger the consultation; detailed descriptions do not.

## Dependencies / Assumptions

- The agent (Claude, GPT, or other) reads and follows tool docstrings when deciding how to use a tool. This is a standard behavior for all major LLM-based agents.
- The `list_filters()` tool is already planned in the base MCP server plan and must be in place before this feature is complete (the agent should reference it during consultation to know valid filter values).
- **The base MCP server data model must be extended** to add three new `list[str]` fields to `RedFlagRecord` / `RedFlagSource`: `industry_types`, `customer_profiles`, and `geographic_footprints`. This is a dependency on the original MCP server plan (2026-03-25). The `search_red_flags` tool signature gains three new optional filter params; `list_filters` returns three new key sets. LLM tagging at ingestion time must be extended to populate these fields. Planning for this consultation feature should treat this data model change as a prerequisite.

## Next Steps

→ `/ce:plan` for structured implementation planning
