---
title: "feat: Add Red Flag Request Routing"
type: feat
status: completed
date: 2026-04-28
origin: docs/brainstorms/2026-04-23-general-chat-aml-redflag-retrieval-requirements.md
---

# feat: Add Red Flag Request Routing

## Overview

Add a deterministic routing helper for AML red flag retrieval so clients can decide whether to ask for more context, use exact metadata filtering, run filtered semantic search, or run direct semantic search. The server remains offline at query time and does not call an LLM; client LLMs may infer filters from prose and pass them into the helper. Semantic search should also be hardened so metadata filters define the eligible set before embedding rank is allowed to decide order.

## Problem Frame

The current MCP server exposes `filter_red_flags` for exact metadata retrieval and `search_red_flags` for semantic relevance. That split is useful, but hosted chat clients still need clear guidance for deciding which tool to call when a user provides some mix of product details, customer/geography/industry metadata, and narrative scenario text. The origin document establishes that exact metadata requests should bypass embeddings and that consultation should happen before retrieval when prompts are vague (see origin: `docs/brainstorms/2026-04-23-general-chat-aml-redflag-retrieval-requirements.md`).

## Requirements Trace

- R1. Provide a first-step routing tool that classifies red flag requests into four routes: needs more context, metadata filter, filtered semantic search, and direct semantic search.
- R2. Keep the routing deterministic and query-time offline; no server-side LLM calls, API keys, sampling, or conversation state.
- R3. Let clients pass filters they inferred from the user request, while making the server responsible for consistent route selection.
- R4. Return structured output that includes the route, rationale, supplied or client-inferred usable filters, missing context, recommended next tool, and recommended arguments.
- R5. Update prompt and tool descriptions so mainstream hosted clients are steered to call the router for ambiguous retrieval requests, while `filter_red_flags` and `search_red_flags` still remain usable directly.
- R6. Ensure filtered semantic search treats metadata filters as eligibility constraints before semantic ranking, so good filtered matches are not lost because they were not near the top of a global vector search.
- R7. Preserve source trust behavior: returned red flag records remain sourced, vector-free, and bounded in claims.

## Scope Boundaries

- The MCP server will not perform free-form prose-to-taxonomy extraction with an LLM.
- The router will not manage multi-turn state; it only evaluates the current query and optional filters.
- MCP elicitation remains optional future UX, not a dependency for the core flow.
- The plan does not change ingestion, embedding generation, source extraction, or taxonomy definitions.

### Deferred to Separate Tasks

- Native MCP elicitation support: separate follow-up work once target client support is proven.
- LLM-backed server-side extraction: future option only if deterministic routing plus client inference proves insufficient.

## Context & Research

### Relevant Code and Patterns

- `src/redflag_mcp/tools.py` contains `RedFlagService`, tool registration, `SEARCH_DESCRIPTION`, and fit explanation logic.
- `src/redflag_mcp/vectorstore.py` contains `RedFlagFilters`, vector search, metadata-only filtering, and list/scalar filter matching.
- `src/redflag_mcp/prompts.py` contains the optional `consult_aml_red_flags` prompt used by clients that support prompt discovery.
- `tests/test_tools.py`, `tests/test_vectorstore.py`, and `tests/test_prompts.py` already test tool metadata, filter behavior, source-free responses, fit explanations, and prompt guidance.
- `AGENTS.md` requires red-green TDD for code implementation and forbids `print()` because stdio transport stdout is the JSON-RPC channel.

### Institutional Learnings

- `docs/brainstorms/2026-03-28-consultation-elicitation-requirements.md` already chose agent-orchestrated consultation over MCP elicitation as the portable baseline.
- `docs/brainstorms/2026-04-23-general-chat-aml-redflag-retrieval-requirements.md` already chose exact metadata filtering for structured requests and semantic search for open-ended relevance.

### External References

- MCP elicitation is a client capability, so it should be additive rather than required for baseline hosted-client behavior: `https://modelcontextprotocol.io/docs/concepts/elicitation`

## Key Technical Decisions

- Deterministic router tool: This gives clients a stable first step without requiring server-side LLM orchestration.
- Client-inferred filters, server-selected route: The client LLM handles prose interpretation; the server applies consistent thresholds and returns the next tool call shape.
- Structured route output over free-text advice: Returning recommended tool arguments reduces the amount of post-classification reasoning the client must perform.
- Metadata eligibility before semantic ranking: Structured applicability fields should constrain candidate eligibility; embeddings should only rank among eligible candidates when filters are present.
- Prompt/tool guidance remains defensive: Some clients may skip the router, so existing tools must still describe when to use direct filtering versus semantic search.

## Open Questions

### Resolved During Planning

- Should the server call an LLM to classify requests? No. The baseline remains deterministic and offline; client LLMs may infer filters and pass them to the router.
- Should elicitation be required for missing context? No. Elicitation is optional because client support varies; normal client follow-up questions remain the compatibility floor.

### Deferred to Implementation

- Exact narrative richness thresholds: Start with simple, tested heuristics, then refine based on observed false positives or false negatives.
- Exact route names and confidence labels: Keep them stable once released, but final string constants can be settled during implementation.

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification. The implementing agent should treat it as context, not code to reproduce.*

| Inputs | Route | Next action |
|--------|-------|-------------|
| Enough filters, weak/no narrative | `metadata_filter` | Call `filter_red_flags` |
| Enough filters, rich narrative | `filtered_semantic_search` | Call `search_red_flags` with filters |
| Not enough filters, weak narrative | `needs_more_context` | Ask one follow-up question |
| Not enough filters, rich narrative | `direct_semantic_search` | Call `search_red_flags` without waiting |

## Implementation Units

- [x] **Unit 1: Add Deterministic Routing Model**

**Goal:** Represent request classification output and shared filter/richness heuristics without coupling them to MCP registration.

**Requirements:** R1, R2, R3, R4

**Dependencies:** None

**Files:**
- Modify: `src/redflag_mcp/models.py`
- Modify: `src/redflag_mcp/tools.py`
- Test: `tests/test_tools.py`

**Approach:**
- Add a small internal routing result shape or response model that can serialize cleanly through FastMCP.
- Use existing filter dimensions from `RedFlagFilters` and existing list/scalar filter semantics.
- Treat product type as a strong applicability signal; treat two or more non-product dimensions as enough structured context; keep source-only filters out of the main four-route routing because they identify corpus provenance rather than institutional applicability.
- Define narrative richness conservatively from the remaining query text: enough meaningful words or scenario-like content should trigger semantic search, while bare taxonomy phrases should not.

**Execution note:** Start with failing tests for each route before adding routing logic.

**Patterns to follow:**
- `RedFlagService.filter_red_flags` validation and clamped-limit behavior in `src/redflag_mcp/tools.py`
- `RedFlagFilters.has_any` in `src/redflag_mcp/vectorstore.py`

**Test scenarios:**
- Happy path: query plus `product_types=["trade_finance"]` and no rich scenario -> route is metadata filter with `filter_red_flags` arguments.
- Happy path: query plus `product_types=["trade_finance"]` and a transaction narrative about invoices or third-party wires -> route is filtered semantic search with `search_red_flags` arguments.
- Happy path: rich narrative with no filters -> route is direct semantic search.
- Happy path: vague query such as "what red flags apply to my crypto product?" with no usable filters -> route is needs more context and includes a follow-up question.
- Edge case: empty strings and empty filter lists are ignored when computing filter sufficiency.
- Edge case: source filters alone do not count as enough institutional metadata for applicability routing.

**Verification:**
- Routing responses are deterministic, JSON-serializable, and do not encode queries when the recommended route is metadata-only or needs-more-context.

- [x] **Unit 2: Expose `classify_red_flag_request` as an MCP Tool**

**Goal:** Register a first-step tool that clients can call before retrieval to get the recommended route and next tool arguments.

**Requirements:** R1, R4, R5

**Dependencies:** Unit 1

**Files:**
- Modify: `src/redflag_mcp/tools.py`
- Test: `tests/test_tools.py`

**Approach:**
- Add `RedFlagService.classify_red_flag_request` and register a FastMCP tool with a description that explicitly says to use it before searching when a user asks which AML red flags apply to a product, customer, geography, industry, scenario, transaction pattern, or institution profile.
- Accept `query`, `limit`, and the same primary metadata filters as `search_red_flags`.
- Return `route`, `confidence`, `reason`, `inferred_filters`, `missing_context`, `recommended_tool`, `recommended_arguments`, and `follow_up_question`.
- Do not call `search_red_flags` or `filter_red_flags` from the classifier; it recommends the next step only.

**Execution note:** Add tool metadata tests first so registration and description changes are locked before implementation.

**Patterns to follow:**
- Existing FastMCP tool registration in `register_tools`
- Existing `test_fastmcp_tool_metadata_includes_consultation_guidance` coverage

**Test scenarios:**
- Happy path: `create_server(...).list_tools()` includes `classify_red_flag_request`.
- Happy path: classifier schema exposes query and primary filter parameters.
- Happy path: tool description names the four possible routes and recommends calling the classifier before ambiguous retrieval.
- Integration: existing tool list tests are updated so adding the new tool does not mask removal of existing tools.

**Verification:**
- Hosted clients can discover the classifier without losing existing retrieval tools.

- [x] **Unit 3: Make Filtered Semantic Search Filter-First**

**Goal:** Prevent filtered semantic search from losing eligible records because LanceDB returned a global vector candidate set before Python list-filtering.

**Requirements:** R6, R7

**Dependencies:** None

**Files:**
- Modify: `src/redflag_mcp/vectorstore.py`
- Test: `tests/test_vectorstore.py`

**Approach:**
- Preserve current vector ranking for unfiltered search and scalar-only where clauses.
- When list filters are present, ensure the candidate pool is derived from all rows matching metadata filters before semantic ordering decides the final result order.
- Keep result shape unchanged: `RedFlagResult` instances include score for semantic search and never include vectors.
- Keep metadata-only filtering deterministic and separate from semantic scoring.

**Execution note:** Add a failing regression test where the only matching list-filtered record would be outside the current `fetch_limit` global vector candidates, then make it pass.

**Patterns to follow:**
- `_matches_filters`, `_all_rows`, and `_row_to_record` in `src/redflag_mcp/vectorstore.py`
- Existing `test_search_applies_list_filters` and `test_filter_red_flags_applies_metadata_without_vector_search`

**Test scenarios:**
- Regression: many globally nearer non-matching records plus one matching filtered record still returns the matching record.
- Happy path: unfiltered vector search remains ranked by semantic distance.
- Happy path: scalar filters still apply and return scored semantic results.
- Edge case: `limit <= 0` and empty tables still return empty lists.

**Verification:**
- Filtered semantic search treats metadata as eligibility, while unfiltered search behavior remains unchanged.

- [x] **Unit 4: Update Client Guidance and Prompt Routing**

**Goal:** Make clients likely to use the classifier while preserving direct tool usability if they skip it.

**Requirements:** R5, R7

**Dependencies:** Unit 2

**Files:**
- Modify: `src/redflag_mcp/tools.py`
- Modify: `src/redflag_mcp/prompts.py`
- Test: `tests/test_tools.py`
- Test: `tests/test_prompts.py`

**Approach:**
- Update `SEARCH_DESCRIPTION` to say `classify_red_flag_request` should be used first for ambiguous "what red flags apply" requests.
- Keep `filter_red_flags` description explicit that exact metadata requests bypass embeddings.
- Update `CONSULT_AML_RED_FLAGS_PROMPT` to describe the four-route policy and explain that missing context should be asked through normal chat unless a client supplies richer elicitation support.
- Keep result-presentation guidance bounded to returned metadata, citations, scores, and fit signals.

**Execution note:** Update prompt/tool metadata tests before changing descriptions.

**Patterns to follow:**
- Existing prompt registration in `src/redflag_mcp/prompts.py`
- Existing metadata assertions in `tests/test_tools.py` and `tests/test_prompts.py`

**Test scenarios:**
- Happy path: search description references the classifier and still references `filter_red_flags` for exact metadata.
- Happy path: consultation prompt names the four routes and says direct semantic search is only for rich narratives with insufficient metadata.
- Edge case: prompt still cautions against overstating legal applicability.

**Verification:**
- Clients receive clear routing guidance through both tool metadata and optional prompt discovery.

## System-Wide Impact

- **Interaction graph:** New classifier sits before retrieval but does not replace existing tools; clients may call classifier, then `filter_red_flags` or `search_red_flags`.
- **Error propagation:** Classifier should return structured guidance for weak inputs instead of raising errors for vague prompts.
- **State lifecycle risks:** No persistent state or conversation memory is added.
- **API surface parity:** Tool registration, prompt guidance, service methods, and tests must all include the new route.
- **Integration coverage:** FastMCP tool metadata tests should prove the new exported tool is discoverable and existing tools remain registered.
- **Unchanged invariants:** `filter_red_flags` remains metadata-only and must not encode queries; `search_red_flags` remains vector-backed and returns vector-free records.

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Clients skip the classifier and call search directly | Keep `search_red_flags` and `filter_red_flags` descriptions independently clear. |
| Deterministic thresholds are too coarse | Keep the router conservative and expose `reason` plus `missing_context` so client behavior is debuggable. |
| Filter-first semantic search becomes inefficient on larger corpora | Start with correctness for the current local corpus; defer indexing/performance work until corpus size demands it. |
| Tool output overstates confidence | Use bounded confidence labels and reasons tied only to supplied filters and query richness. |

## Documentation / Operational Notes

- Update `README.md` if it documents the public tool list or recommended client workflow.
- No new environment variables, API keys, ingestion steps, or transport configuration are required.
- No changes should write to stdout in stdio mode.

## Sources & References

- **Origin document:** [docs/brainstorms/2026-04-23-general-chat-aml-redflag-retrieval-requirements.md](docs/brainstorms/2026-04-23-general-chat-aml-redflag-retrieval-requirements.md)
- Related requirements: [docs/brainstorms/2026-03-28-consultation-elicitation-requirements.md](docs/brainstorms/2026-03-28-consultation-elicitation-requirements.md)
- Related code: `src/redflag_mcp/tools.py`
- Related code: `src/redflag_mcp/vectorstore.py`
- Related tests: `tests/test_tools.py`
- Related tests: `tests/test_vectorstore.py`
- External docs: `https://modelcontextprotocol.io/docs/concepts/elicitation`
