---
title: "feat: Add URL-to-red-flag pipeline script and auto-update registry on extract"
type: feat
status: active
date: 2026-05-17
origin: docs/brainstorms/2026-05-17-url-pipeline-requirements.md
---

# feat: Add URL-to-red-flag pipeline script and auto-update registry on extract

## Overview

Two changes:
1. **Modify `extract.py`** to call `build_registry()` after extraction completes, so `registry.csv` stays up to date whenever `extract.py` is run standalone (batch, range, single-source, parallel — all modes).
2. **Create `scripts/pipeline.py`** with three subcommands (`download`, `extract`, `run`) for a unified URL-to-red-flag workflow that supports download-inspect-extract.

## Problem Frame

Adding new AML sources currently requires running three scripts in sequence with different input formats. A compliance researcher needs both a one-shot pipeline and the ability to download, inspect, then extract. Additionally, running `extract.py` standalone should automatically update the registry without requiring a separate `build_registry.py` run. (see origin: docs/brainstorms/2026-05-17-url-pipeline-requirements.md)

## Requirements Trace

- R1. Accept plain text file, one URL per line, skip blanks and non-http lines
- R2. Download each URL (PDF or web/markdown) using existing harvest logic
- R3. After each successful download, update registry.csv with status `downloaded`
- R4. Extract red flags from downloaded files using existing LLM extraction logic
- R5. After each successful extraction, update registry.csv with status `extracted`
- R6. Dedup against registry.csv `source_url` column; skip if found
- R7. Also update `sources.yaml` and `.extracted_sources.yaml` for consistency
- R8. Support `--force` to bypass dedup
- R9. Support `--parallel N` for parallel extraction (download stays sequential)
- R10. Single pipeline script importing from existing modules
- R11. Three subcommands: `download`, `extract`, `run` (download + extract)
- R12. `extract` subcommand auto-discovers all `downloaded`-status sources from registry.csv
- R13. `extract.py` standalone (all modes: batch, range, parallel, single-source) updates registry.csv after extraction

## Scope Boundaries

- No LanceDB ingestion (remains separate `ingest.py` step)
- No new dependencies
- `extract.py` CLI interface stays identical — only internal behavior changes (registry auto-update)

## Context & Research

### Relevant Code and Patterns

**Harvest functions** (`scripts/harvest_sources.py`):
- `classify_url(url, client)` → `"pdf"` or `"web"`
- `fetch_pdf(url, dest_path, client)` / `fetch_web(url, dest_path, client)`
- `load_registry(path)` / `write_registry(registry, path)` — manages `sources.yaml`
- `next_serial(registry)`, `is_blank_or_invalid(url)`
- Constants: `SOURCES_YAML`, `PDFS_DIR`, `MARKDOWN_DIR`, `USER_AGENT`

**Extract functions** (`scripts/extract.py`):
- `process_one(source, force, manifest, source_url)` → manifest entry dict or None
- `load_manifest()` / `save_manifest(manifest)` — manages `.extracted_sources.yaml`
- `run_batch(force, workers, serial_range)` — batch/parallel/range mode
- `main()` — handles single-source mode, delegates to `run_batch()` for batch
- Two places where extraction completes: end of `run_batch()` (line 597) and end of single-source in `main()` (line 664)

**Registry builder** (`scripts/build_registry.py`):
- `build_registry()` — full rebuild of `registry.csv`. Pure local I/O, no network calls. Safe to call repeatedly.

**Import pattern**: `sys.path.insert(0, scripts_dir)` — used by all existing tests.

## Key Technical Decisions

- **Registry update strategy**: Call `build_registry()` once at end of batch/single-source in `extract.py`, and after each phase in `pipeline.py`. Fast local I/O. (Resolves deferred question from origin doc)
- **Function reuse**: All needed functions importable as-is — no refactoring beyond adding the `build_registry()` call. (Resolves deferred question from origin doc)
- **Dedup in pipeline**: Load `registry.csv` at startup, collect `source_url` values into a set.
- **Subcommand architecture**: `argparse` with `add_subparsers()`.
- **Extract auto-discovery**: Read `registry.csv`, filter `status == "downloaded"`, resolve to local file path.

## Open Questions

### Resolved During Planning

- **How to update registry.csv**: Call `build_registry()` — fast, idempotent, no network.
- **Which functions need refactoring**: None for reuse. `extract.py` gets a small addition (import + call).
- **Where to add registry update in extract.py**: Two call sites — end of `run_batch()` after manifest save, and end of single-source block in `main()` after manifest save.

### Deferred to Implementation

- **Error recovery UX**: If download succeeds but extraction fails, source stays "downloaded". `--force` or re-running `extract` handles this.

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification.*

```
extract.py (modified)
├── run_batch()
│   └── ... existing logic ...
│   └── if new_entries: save_manifest() → build_registry()   # NEW
│
├── main() → single-source path
│   └── ... existing logic ...
│   └── save_manifest() → build_registry()                   # NEW

pipeline.py (new)
├── download(urls_file, force)
│   ├── parse URLs, dedup against registry.csv
│   ├── for each URL: classify → fetch → update sources.yaml
│   └── build_registry()
│
├── extract(force, parallel)
│   ├── load registry.csv → filter status=="downloaded"
│   ├── resolve to local file paths
│   ├── for each: process_one() → save_manifest()
│   └── build_registry()
│
└── run(urls_file, force, parallel)
    ├── download()
    └── extract()
```

## Implementation Units

- [x] **Unit 1: Add registry auto-update to extract.py**

**Goal:** Make `extract.py` call `build_registry()` after successful extraction in all modes (batch, range, parallel, single-source).

**Requirements:** R5, R13

**Dependencies:** None

**Files:**
- Modify: `scripts/extract.py`
- Modify: `tests/test_extract.py`

**Approach:**
- Import `build_registry` from `build_registry` module at top of file
- Add `build_registry()` call at end of `run_batch()`, after `save_manifest()` (inside the `if new_entries:` block, line ~597)
- Add `build_registry()` call at end of single-source path in `main()`, after `save_manifest()` (line ~664)
- Wrap each call in try/except to log but not fail the extraction if registry build fails (defensive — the extraction itself succeeded)

**Patterns to follow:**
- `build_registry.py` is already imported in tests via `sys.path.insert` — same pattern here

**Test scenarios:**
- Batch extraction → `build_registry()` called once after all extractions complete
- Single-source extraction → `build_registry()` called after manifest save
- Extraction with no new entries → `build_registry()` NOT called (nothing changed)
- `build_registry()` failure → logged as warning, extraction result not affected

**Verification:**
- `uv run pytest tests/test_extract.py` passes
- Running `extract.py` in batch mode produces updated `registry.csv` without separate `build_registry.py` call
- All existing extract.py CLI modes still work identically

---

- [x] **Unit 2: Pipeline script with subcommands**

**Goal:** Create `scripts/pipeline.py` with `download`, `extract`, and `run` subcommands.

**Requirements:** R1, R2, R3, R4, R5, R6, R7, R8, R9, R10, R11, R12

**Dependencies:** Unit 1 (extract.py registry update)

**Files:**
- Create: `scripts/pipeline.py`
- Create: `tests/test_pipeline.py`

**Approach:**

*CLI setup:*
- `argparse` with `add_subparsers(dest="command")`
- `download`: positional `urls_file`, optional `--force`
- `extract`: optional `--force`, `--parallel [N]`
- `run`: positional `urls_file`, optional `--force`, `--parallel [N]`

*`download` function (R1, R2, R3, R6, R7, R8):*
- Read URLs from text file, one per line
- Filter with `is_blank_or_invalid()`
- Load registry.csv via `csv.DictReader`, build `source_url` set for dedup
- Load sources.yaml via `harvest_sources.load_registry()`
- For each URL sequentially:
  - Skip if in registry (unless `--force`)
  - `classify_url()` → pdf/web
  - Assign serial key via `next_serial()`
  - `fetch_pdf()` or `fetch_web()`
  - Update sources.yaml dict and `write_registry()`
- Call `build_registry()` once at end
- Return list of newly downloaded source info

*`extract` function (R4, R5, R7, R8, R9, R12):*
- Load registry.csv, filter rows where `status == "downloaded"`
- Resolve each row to local file path (check pdf/ then markdown/ dirs)
- Load manifest and sources registry
- Process each via `extract.process_one()`, sequential or parallel
- After all: `save_manifest()`, `build_registry()`

*`run` function (R11):*
- Call `download()`, then `extract()`

**Patterns to follow:**
- `harvest_sources.py` main() for argparse and httpx.Client context manager
- `extract.py` run_batch() for ThreadPoolExecutor parallel pattern

**Test scenarios:**
- `download`: 2 URLs → both downloaded, registry.csv shows "downloaded"
- `download` dedup: URL already in registry → skipped
- `download --force`: re-downloads
- `extract`: 2 "downloaded" rows → both extracted, registry shows "extracted"
- `extract` with no downloaded rows → clean exit message
- `extract --parallel 2`: runs with 2 workers
- `run`: full flow end-to-end
- Blank/invalid lines → skipped with log
- Download failure → others still processed
- Extraction failure → file stays "downloaded"
- Idempotency: second run → all skipped

**Verification:**
- `uv run pytest tests/test_pipeline.py` passes
- `pipeline.py download` + `pipeline.py extract` ≡ `pipeline.py run`
- registry.csv, sources.yaml, .extracted_sources.yaml all consistent

## System-Wide Impact

- **Interaction graph:** Unit 1 adds a `build_registry` import to `extract.py`. Pipeline calls into harvest, extract, and build_registry modules. Purely imperative, no callbacks.
- **Error propagation:** Download/extract failures logged and skipped. Registry update failures logged but don't fail the extraction.
- **State lifecycle risks:** Crash mid-batch leaves sources.yaml/manifest with last successful entry. Registry.csv rebuilt on next run.
- **API surface parity:** `extract.py` CLI interface unchanged. Existing scripts remain independently usable.

## Risks & Dependencies

- **Rate limiting on downloads**: Sequential download mitigates this.
- **OpenAI API costs**: Dedup is the primary guard. Two-step workflow gives the user a review checkpoint before spending API calls.
- **Circular import risk**: `extract.py` importing from `build_registry.py` — both are scripts, not packages. Since `build_registry` doesn't import from `extract`, no circular dependency.

## Sources & References

- **Origin document:** [docs/brainstorms/2026-05-17-url-pipeline-requirements.md](docs/brainstorms/2026-05-17-url-pipeline-requirements.md)
- Related code: `scripts/harvest_sources.py`, `scripts/extract.py`, `scripts/build_registry.py`
- Related tests: `tests/test_harvest_sources.py`, `tests/test_extract.py`, `tests/test_build_registry.py`
