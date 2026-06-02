---
title: fix: Harden MCP Retrieval Tool Contract
type: fix
status: active
date: 2026-06-01
origin: docs/brainstorms/2026-04-23-general-chat-aml-redflag-retrieval-requirements.md
---

# fix: Harden MCP Retrieval Tool Contract

## Overview

Make the MCP retrieval surface harder for hosted clients to misuse. Keep `search_red_flags`, but stop describing hosted corpus search as semantic when the active corpus path uses lexical BM25 plus alias expansion. Strengthen exact filtering so enumeration work exposes completeness metadata, valid filter values are more discoverable, and source-identity filters are harder to combine incorrectly.

## Problem Frame

Client feedback showed that the current tool contract nudges models toward ranked search even for exact metadata requests. The main causes are misleading "semantic" language in route names and descriptions, bare-string filter parameters with no visible vocabulary, silent limit clamping, and overlapping source-locus filters. This weakens the analyst workflow from the origin document: exact metadata requests should be deterministic and visibly complete, while ranked search should be used for relevance, not enumeration.

## Requirements Trace

- R1. Hosted corpus tools must describe `search_red_flags` as ranked relevance/lexical search, not semantic embedding search.
- R2. `classify_red_flag_request`, prompt guidance, README examples, and tool metadata must use non-semantic route names while preserving the existing tool split between ranked relevance and exact filtering.
- R3. Exact metadata retrieval must expose completeness signals: requested limit, applied limit, returned count, total matched, truncation status, and pagination cursor where deterministic pagination is supported.
- R4. Limit clamping must be explicit in responses so a request for more than `MAX_SEARCH_LIMIT` cannot look complete.
- R5. Category, risk, and list-valued filter vocabularies must be discoverable from tool schemas/descriptions and `list_filters`.
- R6. Source-locus filters must be clarified and guarded: `source_id` is canonical for a source document; `source_url` and `regulatory_source` are alternate source identity filters; `regulator` and `regulator_jurisdiction` are issuer facets.
- R7. Documentation must preserve the distinction between primary `category` and broader `typology_family` relevance, especially for topics such as human trafficking where a record can be relevant without having `category="human_trafficking"`.
- R8. Query-time behavior remains offline and read-only; no server-side LLM, embeddings in hosted corpus mode, write actions, or corpus rebuilds are added.

## Scope Boundaries

- Do not remove `search_red_flags`; clients still need ranked free-text relevance search.
- Do not add a new OR-query DSL or broad topic abstraction in this iteration. For "category OR typology" needs, document the multi-call client pattern and defer a dedicated query language until usage proves it is needed.
- Do not make ingestion models strict validators for every taxonomy value. Existing YAML/corpus workflows intentionally allow controlled-vocabulary growth.
- Do not change source extraction, corpus packaging, Railway configuration, or vector generation.

## Context & Research

### Relevant Code and Patterns

- `src/redflag_mcp/tools.py` owns `RedFlagService`, `SEARCH_DESCRIPTION`, classifier route strings, retrieval response envelopes, FastMCP tool registration, and fit explanation language.
- `src/redflag_mcp/lexicalstore.py` is the active hosted corpus retrieval path. Its `search()` uses FTS/BM25 and alias expansion; `filter_red_flags()` returns deterministic metadata matches.
- `src/redflag_mcp/vectorstore.py` still supports LanceDB embedding search for local/vector mode and should keep behavior compatible where possible.
- `src/redflag_mcp/config.py` contains advisory vocabularies for categories, risk levels, product types, industry types, customer profiles, geographic footprints, typology families, and transaction patterns.
- `src/redflag_mcp/prompts.py` and `README.md` currently still use "semantic" route language.
- `tests/test_tools.py`, `tests/test_lexicalstore.py`, `tests/test_vectorstore.py`, `tests/test_prompts.py`, and `tests/test_models.py` already cover retrieval behavior, tool metadata, prompt guidance, and model serialization.
- `AGENTS.md` requires red-green TDD for code implementation and prohibits `print()` because stdout is the stdio JSON-RPC channel.

### Institutional Learnings

- `docs/plans/2026-04-24-001-feat-hosted-redflag-retrieval-plan.md` established exact metadata filtering as separate from ranked search.
- `docs/plans/2026-04-28-001-feat-red-flag-request-routing-plan.md` added the classifier and filter-first routing, but it predates the hosted lexical corpus release and still names routes as semantic.
- `docs/brainstorms/2026-04-29-redflag-metadata-enrichment-requirements.md` intentionally keeps `typology_family` and `transaction_patterns` extensible, so schema guidance should not over-constrain corpus growth.

## Key Technical Decisions

- Keep one ranked search tool, but make its public contract algorithm-neutral: describe it as "ranked relevance search" and explain that hosted corpus mode is lexical/alias-backed.
- Change canonical classifier route values from `filtered_semantic_search` and `direct_semantic_search` to `filtered_relevance_search` and `direct_relevance_search`.
- Add retrieval metadata to both retrieval tools, but make deterministic pagination a first-class guarantee only for `filter_red_flags`.
- Use `list_filters` as the source of truth for corpus-specific values; add schema/description enum guidance for stable or advisory vocabularies without making YAML ingestion strict.
- Treat source identity filters as mutually exclusive in `filter_red_flags`; issuer facets may combine with any source identity filter using existing AND semantics.

## Public Interface Changes

- `classify_red_flag_request.route` will return `needs_more_context`, `metadata_filter`, `filtered_relevance_search`, or `direct_relevance_search`. The old semantic route strings are intentionally removed from canonical responses and docs rather than preserved as aliases.
- `filter_red_flags` will accept an optional `cursor` argument and return retrieval metadata with `requested_limit`, `applied_limit`, `returned`, `total_matched`, `truncated`, and `next_cursor`.
- `search_red_flags` will keep its existing arguments and add cap/completeness metadata with `requested_limit`, `applied_limit`, `returned`, and `truncated`; it will not accept `cursor` in this iteration.
- `filter_red_flags` will validate that at most one source identity filter is supplied from `source_id`, `source_url`, and `regulatory_source`.
- Tool descriptions and README examples will steer exact category, risk, source, issuer, and taxonomy requests to `filter_red_flags`; ranked free-text relevance remains on `search_red_flags`.

## Open Questions

### Resolved During Planning

- **Should `search_red_flags` be disabled because hosted mode has no embeddings?** No. It should remain available as ranked relevance search, but semantic wording should be removed from the public contract.
- **Should pagination apply to ranked search too?** Only limit/cap transparency should be guaranteed now. Deterministic cursor pagination belongs to exact metadata filtering because ranked search is not the audit/enumeration path.
- **Should source identity filters be collapsed into one argument?** Not in this compatibility pass. Keep existing arguments, make `source_id` canonical, and validate mutually exclusive identity filters.
- **Should old semantic route names remain as aliases?** No. The old names are the source of the client confusion this plan fixes. Existing clients should update to the new canonical relevance route names.

### Deferred to Implementation

- **Exact cursor format:** Use a deterministic opaque string for clients, but choose the internal encoding during implementation after touching `LexicalStore` and vector-store helpers.
- **FastMCP schema expressiveness:** Verify whether the installed FastMCP version preserves `Literal` or `Annotated` metadata in `inputSchema`; use the strongest schema guidance it actually emits.

## Implementation Units

- [ ] **Unit 1: Replace Semantic Route and Search Language**

**Goal:** Make routing and guidance truthful for hosted corpus mode while keeping ranked search available.

**Requirements:** R1, R2, R8

**Dependencies:** None

**Files:**
- Modify: `src/redflag_mcp/tools.py`
- Modify: `src/redflag_mcp/prompts.py`
- Modify: `README.md`
- Test: `tests/test_tools.py`
- Test: `tests/test_prompts.py`

**Approach:**
- Rename route constants and classifier output values to `filtered_relevance_search` and `direct_relevance_search`.
- Update `SEARCH_DESCRIPTION`, classifier description, prompt text, and README tool list to use "ranked relevance search" and "lexical/alias-backed hosted corpus search" rather than "semantic search" or "embedding search" for hosted behavior.
- Preserve `filter_red_flags` as the exact metadata path and `search_red_flags` as the ranked free-text path.
- Update fit explanation fallback text in `tools.py` so corpus and vector paths do not emit "Semantic match" as the default explanation.

**Execution note:** Implement test-first: update failing route/metadata/prompt tests before changing descriptions and constants.

**Patterns to follow:**
- Existing route tests in `tests/test_tools.py`.
- Prompt assertions in `tests/test_prompts.py`.
- Existing tool metadata assertions in `tests/test_tools.py`.

**Test scenarios:**
- Happy path: classifier with rich narrative and filters returns `filtered_relevance_search`, recommends `search_red_flags`, and includes the same recommended arguments as before.
- Happy path: classifier with rich narrative and no filters returns `direct_relevance_search`, recommends `search_red_flags`, and no longer returns semantic route strings.
- Integration: `create_server().list_tools()` descriptions for classifier and search contain relevance/metadata guidance and do not contain `filtered_semantic_search`, `direct_semantic_search`, or "semantic relevance".
- Integration: `consult_aml_red_flags` prompt uses the new route names and tells clients that exact metadata requests go to `filter_red_flags`.
- Regression: existing vague-query and metadata-filter routes remain unchanged.

**Verification:**
- Hosted clients no longer see semantic route names or search descriptions for corpus-backed retrieval.

- [ ] **Unit 2: Add Completeness Metadata and Filter Pagination**

**Goal:** Prevent exact enumeration results from looking complete when the server applied a cap or returned only the first page.

**Requirements:** R3, R4, R8

**Dependencies:** None

**Files:**
- Modify: `src/redflag_mcp/models.py`
- Modify: `src/redflag_mcp/tools.py`
- Modify: `src/redflag_mcp/lexicalstore.py`
- Modify: `src/redflag_mcp/vectorstore.py`
- Test: `tests/test_models.py`
- Test: `tests/test_tools.py`
- Test: `tests/test_lexicalstore.py`
- Test: `tests/test_vectorstore.py`

**Approach:**
- Add a shared retrieval metadata shape for response envelopes: `requested_limit`, `applied_limit`, `returned`, `total_matched` when known, `truncated`, and `next_cursor`.
- Return this metadata from `filter_red_flags` for both lexical and vector-backed stores.
- Add deterministic cursor pagination to `filter_red_flags` using the existing stable metadata sort order. Cursor should advance through the filtered sorted result set and dedupe no records across pages.
- Return cap visibility from `search_red_flags` as well: at minimum `requested_limit`, `applied_limit`, `returned`, and `truncated` when the requested limit exceeds the cap or the known match count exceeds returned results. Do not promise cursor pagination for ranked search in this unit.
- Preserve existing top-level `limit` for backward compatibility during this pass, but make `applied_limit` the clearer contract going forward.

**Execution note:** Implement test-first: start with failing service tests for `limit=50` returning `applied_limit=20` and `truncated=true`, then add store-level pagination tests.

**Patterns to follow:**
- Current limit clamping in `RedFlagService.search_red_flags` and `RedFlagService.filter_red_flags`.
- Deterministic `_metadata_result_sort_key` in `src/redflag_mcp/lexicalstore.py` and `src/redflag_mcp/vectorstore.py`.
- Existing model serialization tests in `tests/test_models.py`.

**Test scenarios:**
- Happy path: `filter_red_flags(category="human_trafficking", limit=2)` over 3 matches returns `returned=2`, `total_matched=3`, `truncated=true`, and a non-null `next_cursor`.
- Happy path: calling `filter_red_flags` with the returned cursor returns the next page without repeating IDs and eventually returns `next_cursor=null`.
- Edge case: `filter_red_flags(limit=50)` returns `requested_limit=50`, `applied_limit=20`, and an explicit truncation signal when more matches exist.
- Edge case: no matches returns `total_matched=0`, `returned=0`, `truncated=false`, and `next_cursor=null`.
- Error path: malformed or stale cursor returns a clear message and empty results rather than raising through MCP.
- Regression: `search_red_flags(limit=50)` exposes that the cap was applied even when search remains unpaginated.
- Integration: corpus mode and vector mode expose the same response metadata keys.

**Verification:**
- Exact metadata queries cannot silently truncate without an explicit completeness signal.

- [ ] **Unit 3: Improve Filter Vocabulary Schema and Validation Guidance**

**Goal:** Make valid filter values discoverable enough that client models choose metadata filtering over free-text search for exact taxonomy requests.

**Requirements:** R5, R7, R8

**Dependencies:** Unit 1 is helpful but not required.

**Files:**
- Modify: `src/redflag_mcp/tools.py`
- Modify: `src/redflag_mcp/config.py`
- Modify: `src/redflag_mcp/prompts.py`
- Modify: `README.md`
- Test: `tests/test_tools.py`
- Test: `tests/test_prompts.py`

**Approach:**
- Use `config.py` vocabularies to enrich tool descriptions and, where FastMCP emits it correctly, input schemas for stable scalar fields such as `risk_level` and `category`.
- Keep list-valued fields typed as `list[str]` unless implementation proves FastMCP can emit item enum guidance without making future corpus values brittle.
- Update `list_filters` description to say it returns valid values from the active local corpus and should be called before exact metadata filtering when the client is uncertain.
- Add explicit category-vs-typology guidance: `category` is a record's primary label; `typology_family` is broader relevance. For "human trafficking category" use `category`; for "trafficking-relevant typologies" use `typology_family` or multiple calls with deduplication.
- Keep validation warnings friendly: unknown values should return no matches or a clear message, not crash the server.

**Execution note:** Implement test-first: assert the exported tool schema/description contains category and risk guidance before changing annotations/descriptions.

**Patterns to follow:**
- Existing advisory vocabulary comments in `src/redflag_mcp/config.py`.
- Tool metadata tests in `tests/test_tools.py`.
- Prompt text coverage in `tests/test_prompts.py`.

**Test scenarios:**
- Integration: `filter_red_flags` input schema or description exposes category values including `human_trafficking` and risk values `high`, `medium`, `low`.
- Integration: `search_red_flags` and classifier metadata steer exact category requests to `filter_red_flags`.
- Happy path: `list_filters` response remains corpus-derived and includes categories and typology families from the active store.
- Edge case: docs/prompt text distinguishes `category="human_trafficking"` from `typology_family=["human_trafficking_proceeds"]`.
- Regression: ingestion/source models still accept free-form `typology_family` values where existing tests require it.

**Verification:**
- A model inspecting the tool schema/description can see that `human_trafficking` is a valid exact category and that typology filters serve broader relevance.

- [ ] **Unit 4: Clarify and Guard Source-Locus Filters**

**Goal:** Reduce inconsistent combinations of source and issuer filters without removing existing public arguments.

**Requirements:** R6, R8

**Dependencies:** Unit 2 is helpful because source-filter pagination should use the same response metadata.

**Files:**
- Modify: `src/redflag_mcp/tools.py`
- Modify: `src/redflag_mcp/lexicalstore.py`
- Modify: `src/redflag_mcp/vectorstore.py`
- Modify: `README.md`
- Test: `tests/test_tools.py`
- Test: `tests/test_lexicalstore.py`
- Test: `tests/test_vectorstore.py`

**Approach:**
- Document canonical meanings in tool descriptions and README:
  - `source_id`: canonical source document identifier from `list_sources`.
  - `source_url`: exact source document URL when the caller has it.
  - `regulatory_source`: exact source title/name when no source ID is available.
  - `regulator`: issuing authority such as FinCEN or FINTRAC.
  - `regulator_jurisdiction`: issuer jurisdiction code such as US, CA, GB, EU.
- Reject or return a clear validation message when more than one source identity filter is provided in one `filter_red_flags` request.
- Allow issuer facets (`regulator`, `regulator_jurisdiction`) to combine with a source identity filter using existing AND semantics.
- Keep `list_sources` as the recommended way to discover `source_id` before source-specific filtering.

**Execution note:** Implement test-first: write failing validation tests for conflicting source identity filters before adding validation logic.

**Patterns to follow:**
- Existing `_validate_filter_cardinality` and no-filter validation in `src/redflag_mcp/tools.py`.
- Source ID generation in `src/redflag_mcp/lexicalstore.py` and `src/redflag_mcp/vectorstore.py`.
- Existing source browsing tests in `tests/test_tools.py`.

**Test scenarios:**
- Happy path: `filter_red_flags(source_id=<id>)` returns only records from that source and includes pagination metadata.
- Happy path: `filter_red_flags(regulator="FinCEN", regulator_jurisdiction="US")` remains valid and applies issuer facets.
- Error path: `filter_red_flags(source_id=<id>, source_url=<url>)` returns a clear message explaining that source identity filters are mutually exclusive.
- Error path: `filter_red_flags(regulatory_source=<title>, source_url=<url>)` returns the same mutual-exclusion message.
- Integration: `filter_red_flags` description names `source_id` as canonical and points to `list_sources`.
- Regression: `get_source` and `list_sources` behavior remains unchanged.

**Verification:**
- Clients have one canonical source-filter path and receive clear feedback when they combine overlapping source identity inputs.

## System-Wide Impact

- **Interaction graph:** Hosted clients may call `classify_red_flag_request`, then either `filter_red_flags` for exact enumeration or `search_red_flags` for ranked relevance. `list_filters` and `list_sources` become stronger prerequisite discovery tools.
- **Error propagation:** Validation failures should return structured MCP payloads with `message` and empty `results`, following existing service behavior.
- **State lifecycle risks:** No persistent state is added. Pagination cursors are stateless and derived from deterministic result ordering.
- **API surface parity:** `tools.py`, `prompts.py`, README examples, and tests must use the same route names and vocabulary language.
- **Integration coverage:** FastMCP tool metadata tests must prove descriptions/schema expose the intended client guidance.
- **Unchanged invariants:** The server remains read-only; hosted corpus mode remains offline and does not encode queries; result records remain vector-free; `filter_red_flags` keeps AND semantics across filters.

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Route renaming surprises existing clients | Treat old semantic names as non-canonical but consider a temporary compatibility field during implementation if tests or docs reveal downstream reliance. |
| Tool descriptions become too long for clients to use well | Keep detailed vocabulary in `list_filters` and README; put only the highest-signal examples in tool descriptions. |
| Cursor pagination becomes inconsistent between lexical and vector stores | Anchor both stores to deterministic metadata sort order for filtering; do not paginate ranked search yet. |
| Strict enums block future corpus growth | Prefer advisory schema/description guidance and corpus-derived `list_filters` over strict validation for extensible list fields. |
| Category-vs-typology remains confusing | Add explicit examples in prompt and README, including human trafficking category vs trafficking-relevant typology. |

## Documentation / Operational Notes

- Update README MCP tool docs and local smoke examples to show exact category enumeration with pagination.
- Update prompt guidance to avoid "semantic" wording and to mention completeness metadata for audit/enumeration requests.
- No Railway redeploy config changes are required beyond the normal push/deploy cycle.
- No corpus rebuild is required unless implementation changes corpus schema, which this plan does not require.

## Sources & References

- **Origin document:** [docs/brainstorms/2026-04-23-general-chat-aml-redflag-retrieval-requirements.md](docs/brainstorms/2026-04-23-general-chat-aml-redflag-retrieval-requirements.md)
- Related plan: [docs/plans/2026-04-24-001-feat-hosted-redflag-retrieval-plan.md](docs/plans/2026-04-24-001-feat-hosted-redflag-retrieval-plan.md)
- Related plan: [docs/plans/2026-04-28-001-feat-red-flag-request-routing-plan.md](docs/plans/2026-04-28-001-feat-red-flag-request-routing-plan.md)
- Related requirements: [docs/brainstorms/2026-04-29-redflag-metadata-enrichment-requirements.md](docs/brainstorms/2026-04-29-redflag-metadata-enrichment-requirements.md)
- Related code: `src/redflag_mcp/tools.py`
- Related code: `src/redflag_mcp/lexicalstore.py`
- Related code: `src/redflag_mcp/vectorstore.py`
- Related code: `src/redflag_mcp/config.py`
- Related tests: `tests/test_tools.py`
- Related tests: `tests/test_lexicalstore.py`
- Related tests: `tests/test_vectorstore.py`
