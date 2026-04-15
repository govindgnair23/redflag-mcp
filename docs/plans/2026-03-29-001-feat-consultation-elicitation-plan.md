---
title: "feat: Add Consultation Elicitation Protocol to search_red_flags"
type: feat
status: active
date: 2026-03-29
origin: docs/brainstorms/2026-03-28-consultation-elicitation-requirements.md
---

# feat: Add Consultation Elicitation Protocol to search_red_flags

## Overview

Extend the `search_red_flags` tool docstring with a consultation protocol that instructs AI agents to ask clarifying questions before searching when a query is too vague. Add three new metadata fields (`industry_types`, `customer_profiles`, `geographic_footprints`) to the data model, enabling richer filtering and more precise results after consultation.

## Problem Frame

When a BSA officer asks "what red flags apply to my crypto product?", the query is too vague for semantic search to return precise results. "Crypto" spans retail exchanges, ATMs, DeFi protocols, institutional custody — each with different risk profiles. The fix is to instruct the AI agent to conduct a brief consultation covering product sub-type, industry type, customer profile, geographic footprint, and transaction channels before constructing a specific search query with structured filters.

(see origin: docs/brainstorms/2026-03-28-consultation-elicitation-requirements.md)

## Requirements Trace

- R1. `search_red_flags` docstring includes a consultation protocol: when the query lacks product specifics, the agent conducts a consultation before calling the tool
- R2. Consultation covers five dimensions: (1) product sub-type, (2) industry type, (3) customer profile, (4) geographic footprint, (5) transaction channels/volumes
- R3. Consultation is conditional: detailed queries skip it; vague queries trigger it
- R4. After consultation, the agent synthesizes answers into both an enriched query and structured filter values for `search_red_flags`
- R5. No new MCP tools, no server-side LLM calls, no conversation state — consultation protocol is entirely in the tool docstring
- Data model prerequisite: add `industry_types`, `customer_profiles`, `geographic_footprints` as `list[str]` fields

## Scope Boundaries

- No new MCP server tools or endpoints
- No server-side question generation, LLM calls, or sampling
- No conversation history or session state between tool calls
- No consultation config file or admin UI
- Agent's own AML domain knowledge supplies the consultation questions — the server does not prescribe exact wording
- Adding `industry_types`, `customer_profiles`, `geographic_footprints` to the data model is a prerequisite change, not the consultation feature itself

## Context & Research

### Relevant Code and Patterns

- `src/redflag_mcp/models.py` — current `RedFlagSource` has `id`, `description`, `product_types`, `regulatory_source`, `risk_level`, `category`, `simulation_type`. New fields follow the same `list[str] | None = None` pattern as `product_types`.
- `src/redflag_mcp/config.py` — exports `RISK_LEVELS` and `SIMULATION_TYPES` enum sets. New dimension enums follow the same pattern.
- `scripts/extract.py` — LLM extraction prompt builds a system prompt with allowed enum values; the same pattern extends to new fields.
- `data/source/*.yaml` — existing YAML files have entries with `product_types` as inline lists; new fields follow the same format.
- Base server plan (2026-03-25-001) Unit 4 — defines the `search_red_flags`, `get_red_flag`, `list_filters` tool signatures. This plan modifies those signatures and docstrings.
- Base server plan Unit 5 — defines `ingest.py` with OpenAI auto-tagging. This plan extends the tagging prompt to populate the three new fields.

### Institutional Learnings

None — `docs/solutions/` does not exist.

## Key Technical Decisions

- **Tool docstring as delivery mechanism**: The consultation protocol lives in the `search_red_flags` docstring, not in a system prompt or separate config. This ensures the behavior travels with the tool definition regardless of which AI agent or platform is in use. (carried from origin doc)

- **Conditional trigger via agent judgment**: The docstring instructs the agent to assess query specificity before triggering consultation. No server-side heuristic or classification — the agent uses its own judgment. (carried from origin doc)

- **Structured filters over query-text-only**: The three new fields enable the agent to pass consultation answers as structured filters (e.g., `industry_types=["msb"]`, `customer_profiles=["retail"]`) rather than just folding them into the query text. This improves precision beyond semantic search alone. (carried from origin doc)

- **Enum sets for new fields**: Define suggested value sets in `config.py` for `INDUSTRY_TYPES`, `CUSTOMER_PROFILES`, and `GEOGRAPHIC_FOOTPRINTS`. These guide the LLM tagging and the agent's filter construction, but are not strictly enforced at the model layer (unlike `risk_level`). This allows organic growth of the taxonomy while maintaining consistency.

## Open Questions

### Resolved During Planning

- **Where does the consultation protocol live?** In the `search_red_flags` tool docstring — the agent reads it and follows it.
- **Should new fields be strictly validated?** No — use suggested enum sets in config for LLM tagging guidance, but don't reject records with values outside the set. The taxonomy will grow as more sources are ingested.
- **How do agents discover valid filter values?** Via `list_filters()`, which already returns distinct values per filterable field. The docstring tells the agent to call it before or during consultation.

### Deferred to Implementation

- **Exact docstring wording**: The consultation protocol wording will need iteration based on testing with Claude and GPT agents. The plan specifies the structure and content; exact phrasing is an implementation detail.
- **LanceDB array filtering for new fields**: The base plan already defers validation of `array_has_any()` syntax for `product_types`. The same approach applies to the three new `list[str]` fields.
- **Backfilling existing YAML data**: Existing extracted YAML files lack the three new fields. They can be backfilled via re-extraction with `--force` or via a one-time `ingest.py` run with LLM auto-tagging. The exact backfill approach is an implementation choice.

## Implementation Units

- [ ] **Unit 1: Extend data model with three new metadata fields**

**Goal:** Add `industry_types`, `customer_profiles`, and `geographic_footprints` as `list[str]` fields to all model layers and config.

**Requirements:** Data model prerequisite for R2, R4

**Dependencies:** Base server plan Unit 1 (models.py and config.py must exist — they do)

**Files:**
- Modify: `src/redflag_mcp/config.py`
- Modify: `src/redflag_mcp/models.py`
- Test: `tests/test_models.py`

**Approach:**
- Add to `config.py`: `INDUSTRY_TYPES` set (e.g., `"depository_institution"`, `"casino"`, `"msb"`, `"securities_broker_dealer"`, `"insurance"`, `"investment_advisor"`, `"real_estate"`, `"crypto_exchange"`, `"fintech"`), `CUSTOMER_PROFILES` set (e.g., `"retail"`, `"commercial"`, `"high_net_worth"`, `"correspondent"`, `"pep"`, `"nonprofit"`), and `GEOGRAPHIC_FOOTPRINTS` set (e.g., `"domestic_us"`, `"cross_border"`, `"high_risk_jurisdiction"`, `"fatf_greylist"`, `"ofac_sanctioned"`)
- Add to `RedFlagSource`: `industry_types: list[str] | None = None`, `customer_profiles: list[str] | None = None`, `geographic_footprints: list[str] | None = None` — same optional pattern as `product_types`
- No strict validation on these fields (unlike `risk_level`). The enum sets are guidance for tagging, not hard constraints.
- When `RedFlagRecord` (LanceModel) and `RedFlagResult` are implemented in the base plan, they must include these three fields as well. Add a note in the plan for the implementer.

**Patterns to follow:**
- `product_types: list[str] | None = None` in current `RedFlagSource`
- `RISK_LEVELS` / `SIMULATION_TYPES` set pattern in `config.py`

**Test scenarios:**
- `RedFlagSource` accepts entries with all three new fields populated
- `RedFlagSource` accepts entries with all three new fields omitted (None)
- Fields accept arbitrary string values (not strictly validated against enum sets)
- Round-trip: construct with new fields, `model_dump()`, reconstruct — values preserved

**Verification:**
- `uv run pytest tests/test_models.py` passes
- New enum sets are importable from `config`

---

- [ ] **Unit 2: Update extraction prompt for new metadata fields**

**Goal:** Extend the `scripts/extract.py` LLM prompt to extract `industry_types`, `customer_profiles`, and `geographic_footprints` for each red flag.

**Requirements:** R2 (five consultation dimensions must be filterable)

**Dependencies:** Unit 1

**Files:**
- Modify: `scripts/extract.py`
- Test: `tests/test_extract.py`

**Approach:**
- In `build_extraction_prompt()`, add three new fields to the Step 2 analysis instructions:
  - `"industry_types"` (list of strings): Which types of financial institutions encounter this indicator? Include allowed values from `INDUSTRY_TYPES`.
  - `"customer_profiles"` (list of strings): Which customer segments does this indicator typically involve? Include allowed values from `CUSTOMER_PROFILES`.
  - `"geographic_footprints"` (list of strings): What geographic risk factors apply? Include allowed values from `GEOGRAPHIC_FOOTPRINTS`.
- Add these fields to the example output in the prompt
- Import the new enum sets from `config.py` and include them in the prompt alongside existing `RISK_LEVELS` and `SIMULATION_TYPES`

**Patterns to follow:**
- Existing extraction prompt structure in `build_extraction_prompt()` — fields listed with type, description, and allowed values
- `{sorted(RISK_LEVELS)}` interpolation pattern for enum sets

**Test scenarios:**
- `build_extraction_prompt()` output contains all three new field names
- `build_extraction_prompt()` output contains at least some allowed values from each new enum set
- `validate_and_build_entries()` accepts entries with the new fields populated
- `validate_and_build_entries()` accepts entries without the new fields (backward-compatible)

**Verification:**
- `uv run pytest tests/test_extract.py` passes
- Manual inspection of prompt output shows the three new fields with clear instructions

---

- [ ] **Unit 3: Extend ingestion auto-tagging for new fields**

**Goal:** Update the `ingest.py` auto-tagging prompt to populate `industry_types`, `customer_profiles`, and `geographic_footprints` when they are missing from source YAML entries.

**Requirements:** R4 (structured filter values must exist in the database)

**Dependencies:** Unit 1, base server plan Unit 5 (ingest.py must exist)

**Files:**
- Modify: `scripts/ingest.py`
- Test: `tests/test_ingest.py`

**Approach:**
- Extend the LLM tagging prompt to request three additional fields in its JSON output: `industry_types`, `customer_profiles`, `geographic_footprints`
- Include the suggested enum values from `config.py` in the prompt
- Apply the same "tag only when missing" logic: if an entry already has `industry_types` populated, don't overwrite it
- The JSON schema sent to the LLM gains three new array fields

**Patterns to follow:**
- Existing tagging logic in `ingest.py` for `product_types`, `regulatory_source`, `risk_level`, `category`

**Test scenarios:**
- Entry with all fields populated (including new ones) — no LLM call
- Entry missing `industry_types` — LLM called; returned values are reasonable
- Entry missing only new fields but having all original fields — LLM called for new fields only (or for all missing, depending on implementation)

**Verification:**
- `uv run pytest tests/test_ingest.py` passes
- After ingestion, `list_filters()` returns non-empty value sets for `industry_types`, `customer_profiles`, and `geographic_footprints`

---

- [ ] **Unit 4: Write the consultation protocol in `search_red_flags` docstring**

**Goal:** Encode the consultation protocol in the `search_red_flags` tool docstring so any AI agent reading the tool definition knows when and how to conduct a pre-search consultation.

**Requirements:** R1, R2, R3, R4, R5

**Dependencies:** Unit 1, base server plan Unit 4 (tools.py must exist with `search_red_flags` tool)

**Files:**
- Modify: `src/redflag_mcp/tools.py`
- Test: `tests/test_tools.py`

**Approach:**

The `search_red_flags` docstring should contain:

1. **Tool purpose**: Search the AML red flag database using natural language and optional metadata filters
2. **Consultation protocol**: When the user's query is vague (mentions a broad product category like "crypto" or "banking" without specifics), conduct a brief consultation before calling this tool:
   - Ask about **product sub-type** (e.g., retail exchange, ATM, DeFi, custody service)
   - Ask about **industry type** (e.g., depository institution, MSB, casino, securities broker-dealer)
   - Ask about **customer profile** (e.g., retail, commercial, high-net-worth, PEP)
   - Ask about **geographic footprint** (e.g., domestic US, cross-border, high-risk jurisdictions)
   - Ask about **transaction channels and volumes** (e.g., ACH, wire, cash, crypto on-ramps, volume thresholds)
3. **Conditional trigger**: Skip the consultation when the query already contains product specifics (e.g., "retail crypto exchange serving US customers with ACH on-ramps")
4. **Post-consultation**: Synthesize answers into (a) an enriched natural-language query for semantic search and (b) structured filter values for `product_types`, `industry_types`, `customer_profiles`, and `geographic_footprints` parameters
5. **Filter discovery**: Recommend calling `list_filters()` before or during consultation to discover valid filter values for all filterable dimensions

The docstring should also update the parameter descriptions:
- Add `industry_types: list[str] | None` — filter by institution type
- Add `customer_profiles: list[str] | None` — filter by customer segment
- Add `geographic_footprints: list[str] | None` — filter by geographic risk factor

The tool function signature gains three new optional parameters that are passed through to `vectorstore.search()`.

**Patterns to follow:**
- Existing tool docstring style in the base plan (clear, imperative, addresses the agent directly)
- Parameter docstring conventions used by FastMCP for JSON schema generation

**Test scenarios:**
- `search_red_flags` tool has a non-empty docstring containing "consultation" or "clarifying"
- `search_red_flags` accepts the three new filter parameters
- `search_red_flags` with new filters passes them through to `vectorstore.search()`
- Calling `search_red_flags` with no filters still works (backward-compatible)
- FastMCP generates a valid JSON schema that includes the new parameters

**Verification:**
- `uv run pytest tests/test_tools.py` passes
- MCP inspector shows the updated tool signature with new parameters and the consultation protocol in the description

---

- [ ] **Unit 5: Update `list_filters` docstring and implementation**

**Goal:** Extend `list_filters` to return values for the three new dimensions and update its docstring to recommend calling it early — before or during consultation.

**Requirements:** Success criteria (agents reference valid filter values during consultation)

**Dependencies:** Unit 1, base server plan Unit 4 (tools.py with `list_filters`)

**Files:**
- Modify: `src/redflag_mcp/tools.py`
- Modify: `src/redflag_mcp/vectorstore.py`
- Test: `tests/test_tools.py`

**Approach:**
- `list_distinct_values()` in `vectorstore.py` already flattens and deduplicates `product_types`. Add the same logic for `industry_types`, `customer_profiles`, and `geographic_footprints`.
- Update the `list_filters` docstring: "Call this tool early — before or during a consultation — to discover valid values for all filterable dimensions: `product_types`, `industry_types`, `customer_profiles`, `geographic_footprints`, `categories`, and `risk_levels`. Use these values to construct precise filters for `search_red_flags`."
- Return dict gains three new keys

**Patterns to follow:**
- Existing `list_distinct_values()` logic for `product_types` (flatten list column, deduplicate, sort)

**Test scenarios:**
- `list_filters()` returns a dict with keys: `product_types`, `industry_types`, `customer_profiles`, `geographic_footprints`, `categories`, `risk_levels`
- All returned value lists are sorted
- New keys return non-empty lists after ingestion of data with the new fields populated

**Verification:**
- `uv run pytest tests/test_tools.py` passes
- MCP inspector: `list_filters()` returns all six dimension keys

---

- [ ] **Unit 6: Update `vectorstore.search()` to accept new filter parameters**

**Goal:** Extend the vector search function to filter on the three new `list[str]` fields.

**Requirements:** R4 (structured filters improve precision)

**Dependencies:** Unit 1, base server plan Unit 3 (vectorstore.py must exist)

**Files:**
- Modify: `src/redflag_mcp/vectorstore.py`
- Test: `tests/test_vectorstore.py`

**Approach:**
- Add `industry_types`, `customer_profiles`, `geographic_footprints` parameters to `search()`, following the same pattern as `product_types`
- Extend the WHERE clause builder to include conditions for the new fields
- Same fallback strategy as `product_types`: if LanceDB SQL array filtering doesn't work, post-filter in Python

**Patterns to follow:**
- Existing `product_types` filter handling in `search()`

**Test scenarios:**
- Filter by `industry_types=["msb"]` — only records with "msb" in their `industry_types` list returned
- Filter by `customer_profiles=["retail"]` — only matching records returned
- Filter by `geographic_footprints=["cross_border"]` — only matching records returned
- Multiple new filters combined — intersection logic (all must match)
- No new filters provided — all results returned (backward-compatible)

**Verification:**
- `uv run pytest tests/test_vectorstore.py` passes
- End-to-end: search with new filters returns a subset of unfiltered results

## System-Wide Impact

- **Interaction graph:** Changes touch the tool interface (docstrings + parameters), data model, vector store search, and ingestion pipeline. No new entry points or middleware. The consultation protocol is agent-side behavior triggered by the docstring — no server callbacks.
- **Error propagation:** New filter parameters are optional; omitting them produces the same behavior as before. Invalid filter values (not in the enum set) should not crash — they simply return no matches (LanceDB WHERE clause finds no rows).
- **State lifecycle risks:** None — no new state. The consultation is stateless from the server's perspective.
- **API surface parity:** The three new parameters on `search_red_flags` and three new keys in `list_filters` output are the only API surface changes. Both are backward-compatible (new params default to None; new output keys are additive).
- **Integration coverage:** End-to-end test: ingest data with new fields populated → call `list_filters` to see new dimension values → call `search_red_flags` with new filters → verify filtered results. Test the consultation protocol by inspecting the docstring content — actual agent behavior is tested manually by asking vague and specific queries.

## Risks & Dependencies

- **Dependency on base server plan**: Units 3–6 require `tools.py`, `server.py`, `vectorstore.py`, and `ingest.py` from the base plan. Units 1–2 can proceed immediately.
- **Docstring length and agent compliance**: Long docstrings risk being truncated or ignored by some LLM agents. The consultation protocol should be concise — a few paragraphs, not a wall of text. Test with both Claude and GPT to verify compliance.
- **Backfilling existing data**: Existing YAML files and any already-ingested LanceDB records lack the three new fields. Running `ingest.py` with auto-tagging populates them. Alternatively, re-extract with `scripts/extract.py --force`. Until backfilled, `list_filters` returns empty lists for the new dimensions, and filters on them match nothing.
- **Enum set evolution**: The suggested value sets for industry types, customer profiles, and geographic footprints are starting points. As more regulatory sources are ingested, the LLM may generate values outside these sets. Since validation is not strict, this is by design — `list_filters` always reflects what's actually in the database.

## Sources & References

- **Origin document:** [docs/brainstorms/2026-03-28-consultation-elicitation-requirements.md](../brainstorms/2026-03-28-consultation-elicitation-requirements.md)
- Base server plan: [docs/plans/2026-03-25-001-feat-aml-redflag-mcp-server-plan.md](2026-03-25-001-feat-aml-redflag-mcp-server-plan.md) (Units 1, 3, 4, 5)
- Extraction plan: [docs/plans/2026-03-26-001-feat-red-flag-extraction-plan.md](2026-03-26-001-feat-red-flag-extraction-plan.md) (already references new fields in R4)
