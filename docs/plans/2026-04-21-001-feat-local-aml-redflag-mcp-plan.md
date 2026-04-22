---
title: "feat: Build Local AML Red Flag MCP with Consultation Metadata"
type: feat
status: active
date: 2026-04-21
origin: docs/brainstorms/2026-03-25-aml-redflag-mcp-requirements.md
supersedes:
  - docs/plans/2026-03-25-001-feat-aml-redflag-mcp-server-plan.md
  - docs/plans/2026-03-29-001-feat-consultation-elicitation-plan.md
related_origins:
  - docs/brainstorms/2026-03-28-consultation-elicitation-requirements.md
---

# feat: Build Local AML Red Flag MCP with Consultation Metadata

## Overview

Build the local MCP server as one integrated slice: structured YAML red flag sources are ingested into a local LanceDB vector store, queried by a FastMCP server, and exposed through three read-only tools. The consultation metadata from the later plan is part of the initial data model and tool surface, not a follow-up migration. This avoids building the base server around a narrower schema and then immediately changing models, filters, ingestion prompts, and tool descriptions.

The first local data set is the three FinCEN-derived YAML files:

- `data/source/001_federal_child_nutrition_fraud.yaml`
- `data/source/002_oil_smuggling_cartels.yaml`
- `data/source/003_bulk_cash_smuggling_repatriation.yaml`

## Problem Frame

Compliance and BSA officers need to ask an agent product- and context-specific AML questions and receive relevant, sourced red flags without knowing the repository taxonomy in advance (see origin: `docs/brainstorms/2026-03-25-aml-redflag-mcp-requirements.md`). The original MCP plan covers the retrieval architecture, while the consultation plan covers a key interaction gap: vague product queries should trigger clarifying questions before search (see related origin: `docs/brainstorms/2026-03-28-consultation-elicitation-requirements.md`).

The current codebase is between those two plans. `src/redflag_mcp/models.py`, `src/redflag_mcp/config.py`, `scripts/extract.py`, and `tests/test_extract.py` exist, but the MCP query path, vector store, embedding layer, and ingestion CLI are not implemented yet. That makes this the right moment to consolidate the schema and tool behavior before building the missing server components.

## Requirements Trace

- R1. Maintain a persistent red flag database with description, source, risk level, category, source URL, optional simulation type, and multi-value dimensions: `product_types`, `industry_types`, `customer_profiles`, and `geographic_footprints`.
- R2. Support semantic search from natural-language context with optional structured filters across product, industry, customer profile, geography, category, and risk level.
- R3. Expose read-only MCP tools: `search_red_flags`, `get_red_flag`, and `list_filters`.
- R4. Return full citation metadata so compliance users can evaluate and reuse results in risk assessment or monitoring design.
- R5. Ingest structured YAML source files into LanceDB, embedding descriptions with `nomic-embed-text-v1.5`.
- R6. Auto-tag missing metadata at ingestion time when `OPENAI_API_KEY` is available; do not mutate source YAML by default.
- R7. Preserve and extend `scripts/extract.py` so future extracted YAML can include consultation metadata.
- R8. Encode a consultation protocol in the `search_red_flags` tool description so agents ask clarifying questions for vague queries and skip consultation for sufficiently specific queries.
- R9. Allow local setup to ingest only the three target YAML files, while keeping a default path that can ingest all curated YAML files later.
- R10. Keep the MCP server offline at query time after ingestion; OpenAI is only required for extraction or ingestion-time auto-tagging.

## Scope Boundaries

- The MCP server is read-only; no MCP write tools for adding or editing red flags.
- No SAR narrative generation, transaction monitoring rule generation, risk scoring, alert disposition, or case management.
- No crawling or automatic refresh from FinCEN or other regulatory sites.
- No server-side consultation state, MCP elicitation callbacks, or server-side LLM calls during user query handling.
- No strict validation of evolving taxonomy values for `industry_types`, `customer_profiles`, or `geographic_footprints`; suggested enums guide extraction and tagging, while stored data remains extensible.

### Deferred to Separate Tasks

- Broader regulatory corpus expansion: add or refresh additional YAML sources after the local MCP path works with the three target files.
- Human review UI for extracted or auto-tagged metadata: useful later, but not required for local MCP viability.
- Hosted deployment, authentication, and multi-user operations: out of scope for a local stdio/HTTP MCP server.

## Context & Research

### Relevant Code and Patterns

- `AGENTS.md` and `CLAUDE.md` define the intended module responsibilities and critical stdout constraint for stdio mode.
- `pyproject.toml` already includes the planned runtime dependencies: `mcp[cli]`, `lancedb`, `sentence-transformers`, `openai`, `pydantic`, `pyyaml`, `pdfplumber`, `httpx`, `beautifulsoup4`, and `python-dotenv`.
- `src/redflag_mcp/config.py` currently defines path constants, embedding dimension, `RISK_LEVELS`, and `SIMULATION_TYPES`.
- `src/redflag_mcp/models.py` currently defines only `RedFlagSource`; `RedFlagRecord` and `RedFlagResult` still need to be added.
- `scripts/extract.py` already extracts red flags from PDFs and URLs into YAML, but its prompt currently omits `industry_types`, `customer_profiles`, and `geographic_footprints`.
- `tests/test_extract.py` covers slugging, manifest behavior, text extraction helpers, YAML writing, and validation. There is no model, vector store, ingestion, embedding, or tool test coverage yet.
- The target YAML files contain 37 red flags total and already include `product_types`, `regulatory_source`, `risk_level`, `category`, and `source_url`; only `001_federal_child_nutrition_fraud.yaml` currently includes `simulation_type`.

### Institutional Learnings

- No `docs/solutions/` directory exists, so there are no prior local learning docs to carry forward.

### Existing Plans Consolidated

- `docs/plans/2026-03-25-001-feat-aml-redflag-mcp-server-plan.md` supplies the base server, LanceDB, embedding, ingestion, and MCP tool architecture.
- `docs/plans/2026-03-29-001-feat-consultation-elicitation-plan.md` supplies the consultation protocol and the richer metadata fields.
- `docs/plans/2026-03-26-001-feat-red-flag-extraction-plan.md` is already partially implemented through `scripts/extract.py`; this plan only carries forward the metadata alignment still missing from extraction.

## Key Technical Decisions

- **Consolidate now instead of layering later**: The consultation plan changes the same model, ingestion, vector store, and tool surfaces that the base MCP plan has not implemented yet. Folding those fields into the first build avoids immediate schema churn.
- **YAML remains canonical; ingestion enriches stored records**: The three target YAML files should be treated as curated source inputs. Ingestion may fill missing fields in the derived LanceDB records, but it should not rewrite source YAML unless a future explicit backfill command is added.
- **Optional rich metadata defaults to empty lists in storage**: Source YAML can omit list fields, but records stored in LanceDB should use consistent list values to simplify distinct-filter generation and post-filtering.
- **Agent-side consultation via tool description**: The server does not own multi-turn consultation. `search_red_flags` tells the calling agent when to ask clarifying questions and how to synthesize answers into an enriched query plus structured filters.
- **OpenAI is ingestion-only for the MCP path**: Query-time behavior remains offline after the vector store exists. If no API key is available during ingestion, already-populated metadata is preserved and missing rich dimensions remain empty with a clear warning.
- **Basic local search and enriched consultation are distinct readiness levels**: The three target YAML files are enough for basic semantic search and citation retrieval. Rich consultation filters for industry, customer profile, and geography require either ingestion-time auto-tagging with `OPENAI_API_KEY` or manually enriched YAML in a later curation pass.
- **Array filtering should have a Python fallback**: LanceDB list-column SQL behavior needs validation against the installed version. The search layer should use native filters where reliable and post-filter in Python where needed.
- **Support explicit local source selection**: The ingestion CLI should be able to ingest the three target files by path so local testing does not accidentally mix in unrelated data from `data/source/`.

## Open Questions

### Resolved During Planning

- **Should the March MCP and consultation plans stay separate?** No. Create this revised consolidated plan and treat consultation metadata as part of the first MCP build.
- **Should missing consultation metadata be written back into YAML?** No for the initial build. Store derived enrichment in LanceDB records during ingestion; keep YAML human-curated unless a later explicit backfill workflow is requested.
- **Is consultation a server-side protocol?** No. It is agent-side behavior delivered through the `search_red_flags` tool description.
- **Which initial data files should drive local verification?** The three target YAML files named in this plan, totaling 37 current records.

### Deferred to Implementation

- **Exact LanceDB list-filter syntax**: Validate native list filtering against the installed LanceDB version; keep Python post-filtering as the fallback.
- **Final consultation wording**: Keep the tool description concise, then iterate after inspecting MCP tool descriptions in the client and testing with vague and specific prompts.
- **Auto-tagging quality**: The suggested enum sets should guide LLM output, but actual field coverage should be checked after ingesting the three target YAML files.
- **CPU-only PyTorch setup**: If dependency installation pulls unsuitable wheels for the target machine, adjust package source configuration during implementation.

## Output Structure

```text
src/redflag_mcp/
  __init__.py
  __main__.py
  config.py
  embeddings.py
  models.py
  server.py
  tools.py
  vectorstore.py
scripts/
  extract.py
  ingest.py
tests/
  test_embeddings.py
  test_extract.py
  test_ingest.py
  test_models.py
  test_tools.py
  test_vectorstore.py
```

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification. The implementing agent should treat it as context, not code to reproduce.*

```mermaid
sequenceDiagram
    participant YAML as data/source target YAML
    participant Ingest as scripts/ingest.py
    participant Tagger as OpenAI tagging
    participant Embed as embeddings.py
    participant DB as LanceDB red_flags table
    participant Server as FastMCP server
    participant Agent as MCP client agent

    Ingest->>YAML: Load selected source files
    Ingest->>Ingest: Validate RedFlagSource records
    alt Missing metadata and OPENAI_API_KEY available
        Ingest->>Tagger: Request missing metadata only
        Tagger-->>Ingest: Product, industry, customer, geography, source, risk, category
    else Metadata complete or no API key
        Ingest->>Ingest: Preserve existing values; warn on missing rich dimensions
    end
    Ingest->>Embed: Encode descriptions with document prefix
    Embed-->>Ingest: Normalized vectors
    Ingest->>DB: Upsert RedFlagRecord rows by id
    Server->>DB: Open table during lifespan
    Agent->>Server: list_filters
    Server-->>Agent: Distinct filter values from stored rows
    Agent->>Agent: Consult user if query is vague
    Agent->>Server: search_red_flags with enriched query and filters
    Server-->>Agent: Ranked RedFlagResult records with citations
```

## Implementation Units

- [x] **Unit 1: Align schema and taxonomy for consultation metadata**

**Goal:** Extend the shared model and config layer so all downstream components can represent the consolidated metadata shape.

**Requirements:** R1, R4, R6, R7

**Dependencies:** None

**Files:**
- Modify: `src/redflag_mcp/config.py`
- Modify: `src/redflag_mcp/models.py`
- Test: `tests/test_models.py`

**Approach:**
- Add suggested enum sets for `INDUSTRY_TYPES`, `CUSTOMER_PROFILES`, and `GEOGRAPHIC_FOOTPRINTS`.
- Extend `RedFlagSource` with optional `industry_types`, `customer_profiles`, and `geographic_footprints` fields.
- Add storage and response models that include all source metadata plus vectors where appropriate.
- Keep `risk_level` and `simulation_type` validation strict, but leave the new list dimensions non-strict so the taxonomy can grow.
- Normalize missing list dimensions to empty lists when building storage records, while keeping source parsing tolerant of omitted fields.

**Patterns to follow:**
- Existing `RedFlagSource` optional field pattern in `src/redflag_mcp/models.py`.
- Existing enum set pattern in `src/redflag_mcp/config.py`.

**Test scenarios:**
- Happy path: a source record with all rich metadata validates and preserves all list values.
- Happy path: a source record from one of the three target YAML files validates even when rich metadata is omitted.
- Edge case: missing rich list fields convert to empty lists when preparing a storage record.
- Error path: invalid `risk_level` is rejected.
- Error path: invalid `simulation_type` is rejected.
- Integration: converting a storage record to an MCP result drops the vector while preserving citation metadata.

**Verification:**
- Model tests cover current YAML compatibility and the richer consolidated schema.

---

- [x] **Unit 2: Update extraction metadata output for future sources**

**Goal:** Bring the already-existing extraction script back into alignment with the consolidated schema so future YAML outputs can include consultation dimensions.

**Requirements:** R7

**Dependencies:** Unit 1

**Files:**
- Modify: `scripts/extract.py`
- Test: `tests/test_extract.py`

**Approach:**
- Extend the extraction prompt to ask for `industry_types`, `customer_profiles`, and `geographic_footprints`.
- Include the suggested enum sets in the prompt alongside `RISK_LEVELS` and `SIMULATION_TYPES`.
- Keep validation backward-compatible so current YAML files without the new fields still pass.
- Do not change the extraction script into an ingestion or backfill tool; it remains an upstream YAML producer.

**Patterns to follow:**
- Current prompt construction and validation flow in `scripts/extract.py`.
- Existing `validate_and_build_entries` behavior that skips invalid entries without aborting the entire source.

**Test scenarios:**
- Happy path: the generated prompt contains all three rich metadata field names.
- Happy path: the generated prompt includes representative allowed values from each new enum set.
- Happy path: validation accepts LLM output with the new fields populated.
- Edge case: validation accepts older output that omits all three new fields.
- Error path: output with an invalid strict scalar field is still skipped and counted.

**Verification:**
- Extraction tests prove prompt/schema alignment without requiring a live OpenAI call.

---

- [x] **Unit 3: Implement embeddings and vector store with robust filtering**

**Goal:** Add the local embedding layer and LanceDB access layer needed to persist, query, filter, and inspect red flag records.

**Requirements:** R2, R4, R5, R9, R10

**Dependencies:** Unit 1

**Files:**
- Create: `src/redflag_mcp/embeddings.py`
- Create: `src/redflag_mcp/vectorstore.py`
- Test: `tests/test_embeddings.py`
- Test: `tests/test_vectorstore.py`

**Approach:**
- Load `nomic-embed-text-v1.5` once per process and apply the model's document/query task prefixes consistently.
- Store normalized vector lists compatible with LanceDB.
- Create or open a `red_flags` table using the storage model.
- Upsert by `id` so repeated ingestion does not duplicate records.
- Implement semantic search with optional filters for product, industry, customer profile, geography, category, and risk level.
- Prefer native LanceDB filtering for scalar fields and reliable list filters; post-filter list fields in Python if native list SQL is unavailable or unstable.
- Return stable, sorted distinct filter values by flattening list fields and deduplicating scalar fields.
- Keep normal unit tests independent of the real embedding model by allowing a fake encoder/model; reserve the real model download for an explicit integration or smoke check.

**Patterns to follow:**
- Module responsibilities in `AGENTS.md`.
- Existing path constants from `src/redflag_mcp/config.py`.

**Test scenarios:**
- Happy path: document and query encoders apply the expected prefixes and return vectors of the configured embedding dimension with a fake model.
- Happy path: repeated upsert of the same `id` updates one record instead of creating duplicates.
- Happy path: semantic search returns ranked results from seeded records.
- Happy path: scalar filters return only matching risk levels and categories.
- Happy path: list filters return only records matching product, industry, customer profile, or geography.
- Edge case: empty filter lists are treated like no filter.
- Edge case: search against an empty table returns an empty result set without crashing.
- Integration: distinct filter listing returns sorted values for all filterable dimensions.

**Verification:**
- Vector store tests use temporary storage and do not create or depend on `data/vectors/`.

---

- [x] **Unit 4: Add ingestion CLI for selected YAML sources and derived enrichment**

**Goal:** Create the ingestion path that turns the three target YAML files into searchable LanceDB records, enriching missing metadata only when needed and possible.

**Requirements:** R1, R5, R6, R9, R10

**Dependencies:** Unit 1, Unit 3

**Files:**
- Create: `scripts/ingest.py`
- Test: `tests/test_ingest.py`

**Approach:**
- Load YAML records from explicit file paths when provided, and default to curated YAML files under `data/source/` when no paths are provided.
- Validate every entry through `RedFlagSource`; log invalid entries by file and id while continuing with other valid entries.
- Detect missing metadata across product, industry, customer profile, geography, regulatory source, risk level, and category.
- When `OPENAI_API_KEY` is available, request only missing metadata and merge returned values into derived records.
- When `OPENAI_API_KEY` is absent, ingest records with available metadata and warn clearly when rich dimensions remain empty.
- Do not modify source YAML files during normal ingestion.
- Encode descriptions and upsert storage records into LanceDB by id.
- Use logging for status and warnings so this code can be reused safely near stdio server contexts.

**Patterns to follow:**
- OpenAI client usage and JSON response mode from `scripts/extract.py`.
- Path constants from `src/redflag_mcp/config.py`.
- No-stdout-in-server constraint from `AGENTS.md`; ingestion can be a CLI, but shared helpers should still use logging.

**Test scenarios:**
- Happy path: ingesting the three target YAML files produces 37 valid storage records before any invalid-entry skips.
- Happy path: records with complete metadata do not trigger an LLM tagging request.
- Happy path: records missing only rich dimensions are enriched when a mocked tagging response supplies them.
- Edge case: explicit source file selection ingests only those files and excludes other YAML files under `data/source/`.
- Edge case: missing API key preserves existing metadata and leaves missing rich dimensions empty with a warning.
- Error path: malformed YAML or invalid records are reported without aborting other files.
- Integration: running ingestion twice with the same ids leaves one stored row per id.

**Verification:**
- The ingestion path can populate `data/vectors/` from the three target files and leave source YAML unchanged.

---

- [x] **Unit 5: Implement FastMCP server and read-only tools**

**Goal:** Expose the local red flag database through MCP with consultation-aware search behavior and citation-preserving results.

**Requirements:** R2, R3, R4, R8, R10

**Dependencies:** Unit 1, Unit 3, Unit 4

**Files:**
- Create: `src/redflag_mcp/server.py`
- Create: `src/redflag_mcp/tools.py`
- Modify: `src/redflag_mcp/__init__.py`
- Modify: `src/redflag_mcp/__main__.py`
- Test: `tests/test_tools.py`

**Approach:**
- Build a FastMCP app with lifespan-managed access to the embedding model and LanceDB table.
- Support stdio by default and HTTP via `MCP_TRANSPORT`, `MCP_HOST`, and `MCP_PORT`.
- Register three read-only tools: search, get-by-id, and list filters.
- Make `search_red_flags` accept an enriched natural-language query plus optional filters for product, industry, customer profile, geography, category, and risk level.
- Keep the `search_red_flags` description concise but explicit: vague queries should trigger a brief agent-led consultation covering product sub-type, industry, customer profile, geography, and transaction channels/volumes; specific queries should search directly.
- Make `list_filters` return all filterable dimensions and tell agents to call it before or during consultation.
- Make `get_red_flag` return one citation-preserving record or a clear not-found response.
- Handle the pre-ingestion state gracefully with helpful tool responses rather than server crashes.
- Ensure package entry points consistently reach the server main function.

**Patterns to follow:**
- FastMCP server/tool pattern from the MCP dependency already listed in `pyproject.toml`.
- Module responsibilities in `AGENTS.md`.

**Test scenarios:**
- Happy path: `list_filters` returns product, industry, customer profile, geography, category, and risk values from seeded records.
- Happy path: `search_red_flags` returns no more than the requested limit and includes citation metadata.
- Happy path: search with rich filters passes those filters to the vector store and excludes non-matching records.
- Happy path: `get_red_flag` returns a matching seeded record without vector data.
- Edge case: excessive limits are clamped to a safe maximum.
- Edge case: no filters still performs semantic search.
- Error path: missing or empty LanceDB table returns a helpful pre-ingestion message.
- Integration: FastMCP tool metadata includes the consultation guidance and new filter parameters.

**Verification:**
- The MCP inspector can load the server and show the three expected tools with consultation-aware descriptions.

---

- [x] **Unit 6: Local MCP smoke test and documentation**

**Goal:** Make the local workflow reproducible for a developer or compliance reviewer using the three target YAML files.

**Requirements:** R3, R4, R8, R9, R10

**Dependencies:** Unit 4, Unit 5

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`
- Test: `tests/test_tools.py`

**Approach:**
- Document the local flow: dependency installation, ingesting the three target YAML files, starting the MCP server, and verifying tools.
- Document that `OPENAI_API_KEY` is only needed for extraction and ingestion-time enrichment of missing fields.
- Document that source YAML is not rewritten by ingestion.
- Add a small set of manual smoke-test prompts that cover filter discovery, a specific search, a vague query that should trigger consultation, and a get-by-id lookup.
- Keep `AGENTS.md` aligned with the actual implemented modules and any CLI source-selection behavior added during ingestion.

**Patterns to follow:**
- Existing command and architecture sections in `AGENTS.md`.

**Test scenarios:**
- Integration: after ingesting the three target files, `list_filters` exposes non-empty values for dimensions populated by source data or auto-tagging.
- Integration: without `OPENAI_API_KEY`, basic semantic search and citation retrieval still work, while rich consultation filter lists may be empty and documented as not yet enriched.
- Integration: with mocked or real enrichment, `list_filters` exposes non-empty industry, customer profile, and geography values for the three target files.
- Integration: a specific query about federal benefit program fraud returns child-nutrition records with FinCEN citation metadata.
- Integration: a query about southwest-border oil or bulk-cash activity returns records from the oil smuggling or bulk cash source files.
- Manual behavior: a vague product query should cause the calling agent to consult before search; a detailed query should search directly.

**Verification:**
- A fresh local setup can ingest the three target YAML files, start the MCP server, and retrieve sourced results through MCP tools.

## System-Wide Impact

- **Interaction graph:** `scripts/extract.py` produces YAML; `scripts/ingest.py` reads YAML, enriches and embeds derived records, then writes LanceDB; `server.py` opens the derived store; `tools.py` exposes read-only MCP access. The source and query workflows remain separate.
- **Error propagation:** Extraction and ingestion should report file, validation, network, and API failures clearly. MCP tools should return helpful tool-level messages for missing data rather than crashing the server.
- **State lifecycle risks:** Repeated ingestion must be idempotent by record id. Source YAML must not be mutated by default. Derived LanceDB state can be regenerated from YAML plus optional auto-tagging.
- **API surface parity:** Adding rich metadata affects source models, storage models, result models, vector filters, filter discovery, extraction prompts, ingestion prompts, and MCP tool metadata. All surfaces must move together.
- **Integration coverage:** Unit tests alone will not prove the pipeline. The critical verification path is target YAML files to ingestion, LanceDB, `list_filters`, `search_red_flags`, and `get_red_flag`.
- **Unchanged invariants:** The MCP server remains read-only and offline at query time. Stdio stdout remains reserved for JSON-RPC; server code must use logging, not `print()`.

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Rich metadata is missing from current YAML files | Ingestion auto-tags derived records when an API key is available; otherwise it warns and still ingests searchable records with empty rich dimensions. |
| Users expect full consultation filters without enrichment | Document the two readiness levels: basic semantic search works from current YAML, while rich consultation filters need auto-tagging or manual metadata curation. |
| LanceDB list filtering is version-sensitive | Keep list filtering behind a helper and fall back to Python post-filtering after fetching a larger candidate set. |
| Long tool descriptions may be ignored or truncated by agents | Keep consultation guidance concise and verify the rendered tool description in an MCP client. |
| First embedding model download slows setup | Trigger model download during ingestion so the server does not block on first desktop connection. |
| OpenAI tagging introduces non-deterministic metadata | Preserve source YAML, constrain prompts with suggested enum values, and expose actual stored values through `list_filters`. |
| Source selection accidentally ingests unrelated YAML files | Support explicit source paths and use the three target files for local smoke tests. |

## Documentation / Operational Notes

- Update README setup instructions only after the implemented commands and entry points are real.
- Keep `data/vectors/` derived and gitignored.
- Treat the three target YAML files as the local demonstration corpus for this plan.
- Do not import CLI scripts into server modules. Server modules and shared helpers used by the server must use logging and must not write to stdout in stdio mode.

## Sources & References

- **Origin document:** [docs/brainstorms/2026-03-25-aml-redflag-mcp-requirements.md](../brainstorms/2026-03-25-aml-redflag-mcp-requirements.md)
- **Related origin:** [docs/brainstorms/2026-03-28-consultation-elicitation-requirements.md](../brainstorms/2026-03-28-consultation-elicitation-requirements.md)
- **Superseded plan:** [docs/plans/2026-03-25-001-feat-aml-redflag-mcp-server-plan.md](2026-03-25-001-feat-aml-redflag-mcp-server-plan.md)
- **Superseded plan:** [docs/plans/2026-03-29-001-feat-consultation-elicitation-plan.md](2026-03-29-001-feat-consultation-elicitation-plan.md)
- **Related extraction plan:** [docs/plans/2026-03-26-001-feat-red-flag-extraction-plan.md](2026-03-26-001-feat-red-flag-extraction-plan.md)
- **Target source:** `data/source/001_federal_child_nutrition_fraud.yaml`
- **Target source:** `data/source/002_oil_smuggling_cartels.yaml`
- **Target source:** `data/source/003_bulk_cash_smuggling_repatriation.yaml`
- **Project instructions:** `AGENTS.md`
