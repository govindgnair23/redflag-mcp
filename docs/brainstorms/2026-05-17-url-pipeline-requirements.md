---
date: 2026-05-17
topic: url-pipeline
---

# URL-to-Red-Flag Pipeline

## Problem Frame

Adding new AML sources currently requires running three separate scripts in sequence (harvest, extract, build_registry), each with different input formats. A compliance researcher with a list of URLs should be able to run a single command and have all sources downloaded, red flags extracted, and the registry updated — with automatic deduplication so re-runs are safe. The researcher also needs the option to download first, inspect the files, and extract later.

## Requirements

- R1. Accept a plain text file where each line is one URL. Blank lines and lines not starting with `http://` or `https://` are skipped.
- R2. For each URL, download the source (PDF or web/markdown) using existing harvest logic (classify URL, fetch PDF or fetch via Jina Reader).
- R3. After each successful download, update `registry.csv` with status `downloaded`.
- R4. Extract red flags from downloaded files using existing LLM extraction logic.
- R5. After each successful extraction, update `registry.csv` with status `extracted` and populate red_flag_count, output_file, slug, and extracted_at.
- R6. Deduplication: before downloading, check `registry.csv` for the URL. If found (any status), skip that URL. Log the skip.
- R7. Also update `sources.yaml` and `.extracted_sources.yaml` so the existing per-script workflows remain consistent.
- R8. Support `--force` flag to bypass deduplication and re-process URLs.
- R9. Support `--parallel N` flag for parallel extraction (download stays sequential to avoid rate limiting).
- R10. Implemented as a single `scripts/pipeline.py` that imports and reuses functions from existing modules (harvest_sources.py, extract.py, build_registry.py).
- R11. Support three subcommands: `download`, `extract`, and `run` (download + extract).
- R12. The `extract` subcommand auto-discovers all sources with status `downloaded` in `registry.csv` (no input file required).

## Success Criteria

- `pipeline.py run urls.txt` with 5 URLs downloads all 5, extracts red flags, and produces a fully updated `registry.csv`.
- `pipeline.py download urls.txt` downloads only, leaving status as `downloaded`.
- `pipeline.py extract` finds all `downloaded` sources in registry.csv and extracts them.
- Running any command again with the same URLs produces zero downloads and zero extractions (all skipped).
- `--force` re-processes everything.
- Existing scripts (`harvest_sources.py`, `extract.py`, `build_registry.py`) continue to work independently.

## Scope Boundaries

- No ingestion into LanceDB (remains a separate `ingest.py` step).
- No changes to existing script interfaces or behavior.
- No new dependencies.

## Key Decisions

- **Input format**: Plain text file (one URL per line), not CSV. Simpler for ad-hoc use.
- **Dedup source of truth**: `registry.csv` URL column. Single authoritative view.
- **Architecture**: Single script importing from existing modules, not a subprocess orchestrator. Enables clean state passing between steps and incremental registry updates.
- **Registry updates**: Incremental (after each source), not batch-at-end. If the script crashes mid-run, already-processed sources are reflected in the registry.
- **Subcommands**: `download`, `extract`, `run`. Allows download-inspect-extract workflow. Extract auto-discovers from registry.csv.
- **Extract scope**: Auto-discovers all `downloaded`-status rows in registry.csv. No input file needed for extract.

## Outstanding Questions

### Deferred to Planning

- [Affects R3, R5][Technical] How to incrementally update registry.csv without a full rebuild — either append rows and re-sort, or call `build_registry()` after each step.
- [Affects R10][Needs research] Which functions from harvest_sources.py and extract.py can be imported directly vs. need light refactoring for reuse.

## Next Steps

-> `/ce:plan` for structured implementation planning
