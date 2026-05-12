---
title: "feat: CSV Source Harvester — download PDFs and capture web pages from AML catalog"
type: feat
status: completed
date: 2026-05-11
origin: docs/brainstorms/2026-05-10-csv-source-harvester-requirements.md
---

# feat: CSV Source Harvester

## Overview

A new standalone script, `scripts/harvest_sources.py`, that reads the Global AML/CFT/Sanctions Red Flag Catalog CSV, classifies each URL as a PDF or web page, downloads PDFs to `red_flag_sources/pdfs/`, fetches web pages as markdown via the Jina Reader API to `red_flag_sources/markdown/`, and registers each new entry in `sources.yaml`. Existing entries are skipped via URL-level deduplication. The script is idempotent: re-running against the same CSV produces no new files or registry entries.

## Problem Frame

The catalog CSV lists ~218 authoritative regulatory documents (FATF, FCA, EBA, MAS, AUSTRAC, NCA, OFAC, etc.). The existing pipeline only covers 38 FinCEN PDFs. Without automated harvesting, building a broader corpus requires manual per-URL work. This script automates that acquisition step and populates the source materials that feed `scripts/extract.py` → `scripts/ingest.py` → the vector store. (see origin: `docs/brainstorms/2026-05-10-csv-source-harvester-requirements.md`)

## Requirements Trace

- R1. Accepts a CSV file path as a single positional CLI argument.
- R2. Reads the `Direct URL` column from each row.
- R3. Deduplicates against all URL values currently in `sources.yaml`.
- R4. Skips blank or malformed URLs with a logged warning.
- R5. Classifies URLs as PDF via heuristics; falls back to HTTP HEAD for ambiguous cases.
- R6. Downloads PDFs to `red_flag_sources/pdfs/NNN.pdf`.
- R7. Fetches web pages via Jina Reader and saves to `red_flag_sources/markdown/NNN.md`.
- R8. Appends each successful entry to `sources.yaml` (URL-only schema preserved).
- R9. Skips failed URLs without crashing; logs errors per URL.
- R10. Idempotent on repeated runs against the same CSV.
- R11. Prints a final summary: PDFs downloaded, web pages fetched, skipped (existing), failed.
- R12. Auto-creates `red_flag_sources/pdfs/` and `red_flag_sources/markdown/` if absent.

## Scope Boundaries

- Does not parse or extract red flag content from downloaded files — that is `scripts/extract.py`.
- Does not follow embedded links inside fetched web pages (no recursive crawl).
- Does not modify `red_flag_sources/pdflinks.txt` — that file remains the hand-curated FinCEN list.
- Does not add metadata fields (title, region, type) to `sources.yaml` entries — URL-only schema.
- Does not check redistribution rights; that remains a maintainer responsibility.
- Does not rate-limit between requests in v1 — left as a future enhancement.

## Context & Research

### Relevant Code and Patterns

- `scripts/build_sources_registry.py` — canonical pattern for reading, mutating, and fully overwriting `sources.yaml` via `yaml.safe_load` / `yaml.dump(sort_keys=True, allow_unicode=True, default_flow_style=False)`.
- `scripts/extract.py` — established `httpx` client pattern: `httpx.get(url, timeout=30.0, headers={"User-Agent": "Mozilla/5.0 ..."}, follow_redirects=True)`. The project uses `httpx` exclusively; no `requests`.
- `scripts/ingest.py` — canonical argparse structure: `argparse.ArgumentParser`, positional `type=Path` arg, `logging.basicConfig` called inside `main()`, `LOGGER = logging.getLogger(__name__)` at module level.
- `red_flag_sources/sources.yaml` — existing registry with keys `'001'`–`'038'`, each mapping to `{url: <string>}`.
- All scripts anchor paths via `PROJECT_ROOT = Path(__file__).resolve().parent.parent`.
- Directory creation uses `path.mkdir(parents=True, exist_ok=True)`.
- Binary file writes use `path.write_bytes(response.content)`.

### Institutional Learnings

- No `docs/solutions/` directory exists in this project. Learnings are embedded in script code and prior brainstorm docs.
- YAML files are always read-modify-written in full (never opened in append mode — YAML requires a coherent document).
- The `sources.yaml` key format is a zero-padded three-digit string (`f"{n:03d}"`), matching the `data/source/NNN_*.yaml` naming scheme.
- There is zero subprocess usage anywhere in `scripts/` — the Jina fetch should use `httpx` directly (see Key Technical Decisions).

### External References

- Jina Reader API: `GET https://r.jina.ai/{target_url}` returns cleaned markdown. No API key required for standard use. No special `Accept` header needed — markdown is the default response format.

## Key Technical Decisions

- **httpx for Jina fetch, not subprocess**: The requirements doc specified `curl -s https://r.jina.ai/{url}`, but `httpx` (already a project dependency) can perform the same GET with no subprocess overhead, no shell injection risk, and consistent error handling. Resolution: use `httpx.get(f"https://r.jina.ai/{url}", ...)` throughout. (see origin: R7, deferred question on Jina headers)

- **PDF detection order — heuristics then HEAD**: Static string checks on the URL path cover the patterns present in this catalog. Only fall back to a HEAD request when heuristics are inconclusive. This avoids an extra round-trip for the majority of URLs that have `.pdf` in their path. (see origin: R5)

  Heuristic patterns (applied in order):
  1. URL path ends with `.pdf` (case-insensitive) — catches most direct PDF links.
  2. URL path contains `/download` — covers all OFAC variants (`/download`, `/download?inline`, `/download?inline=`).
  3. URL path ends with `/file` — covers NCA Red/Amber Alert direct downloads.

  HEAD fallback: `httpx.head(url, follow_redirects=True, timeout=15.0)` → check `Content-Type: application/pdf`.

  The `/download` heuristic is *not* host-scoped. In this catalog all `/download` URLs are from `ofac.treasury.gov`, but the HEAD fallback corrects any false positives on other sites. (see origin: deferred question on host-scoping)

- **YAML written once at end via try/finally**: Writing after every URL would mean 218 full rewrites. Writing at the end means a crash before completion leaves the downloaded files on disk but the new keys un-registered. On next run, those URLs are not yet in `sources.yaml` so they are re-fetched (overwriting the same file contents — harmless). This is consistent with `build_sources_registry.py`'s full-overwrite approach. (see origin: R8, R10)

- **File naming: key-only (`NNN.pdf`, `NNN.md`)**: No title slug in filenames. The registry key is the single identifier — look up the URL via `sources.yaml`. Consistent with the deferred decision to keep sources.yaml URL-only. (see origin: deferred question on file naming)

- **Timeouts**: PDF downloads — 60s (large regulatory PDFs can be 10+ MB; 30s is too short). HEAD requests — 15s. Jina web fetches — 30s. All use `follow_redirects=True` and a browser `User-Agent`.

- **No dry-run flag in v1**: The script is safe to run (dedup prevents re-downloads) and cheap to re-run. Dry-run adds complexity without clear v1 value.

## Open Questions

### Resolved During Planning

- **Jina via httpx vs subprocess**: Resolved — use httpx (see Key Technical Decisions above).
- **`/download` host-scoping**: Resolved — keep heuristic un-scoped; HEAD fallback corrects edge cases.
- **File naming**: Resolved — key-only (`NNN.pdf` / `NNN.md`).
- **Jina Accept header**: Resolved — not needed; Jina returns markdown by default.
- **PDF download timeout**: Resolved — 60s for downloads, 15s for HEAD, 30s for Jina.
- **YAML write timing**: Resolved — single write at the end via `try/finally`.

### Deferred to Implementation

- Whether `httpx.Client` should be used as a context manager (session reuse) or whether per-request `httpx.get()` calls are sufficient. Either works; session reuse is marginally faster but adds setup. Decide based on observed performance during testing.
- Whether to add `--timeout-pdf`, `--timeout-web` CLI flags for operator tuning. Omit in v1; add if needed.
- Exact `User-Agent` string — mirror whatever `extract.py` uses (check at implementation time).

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification. The implementing agent should treat it as context, not code to reproduce.*

```
main(argv)
  ├── parse args → csv_path: Path
  ├── load_registry(sources_yaml) → registry: dict[str, dict], existing_urls: set[str]
  │     next_serial = max(int(k) for k in registry) + 1  (or 1 if empty)
  ├── open csv_path, DictReader on "Direct URL" column
  ├── for each url in CSV:
  │     if blank / not http* → skip (warn)
  │     if url in existing_urls → skip (info, inc skipped)
  │     classify url:
  │       heuristic_is_pdf(url)? → True → fetch_pdf(url) → pdfs/NNN.pdf
  │                              → False → head_is_pdf(url)? → True → fetch_pdf
  │                                                          → False → fetch_web(url) → markdown/NNN.md
  │       on fetch success:
  │         registry[f"{serial:03d}"] = {"url": url}
  │         existing_urls.add(url)
  │         inc pdf_count or web_count; serial += 1
  │       on fetch failure:
  │         LOGGER.error(...); inc failed_count; continue
  ├── [finally] write_registry(registry, sources_yaml)
  └── log summary: pdf_count, web_count, skipped_count, failed_count
```

## Implementation Units

- [x] **Unit 1: Script skeleton and YAML registry I/O**

**Goal:** Create `scripts/harvest_sources.py` with CLI argument parsing, project path constants, directory setup, and the `load_registry` / `write_registry` helpers.

**Requirements:** R1, R8, R10, R12

**Dependencies:** None

**Files:**
- Create: `scripts/harvest_sources.py`
- Create: `tests/test_harvest_sources.py`

**Approach:**
- `from __future__ import annotations` at top (matches all other scripts).
- `PROJECT_ROOT`, `SOURCES_YAML`, `PDFS_DIR`, `MARKDOWN_DIR` as module-level constants derived from `Path(__file__).resolve().parent.parent`.
- `load_registry(path)` reads `sources.yaml` via `yaml.safe_load`, guards against empty/missing file, returns `(registry_dict, existing_urls_set)` where `existing_urls_set` is the set of all URL values already registered.
- `write_registry(registry, path)` does a full overwrite using `yaml.dump(registry, f, default_flow_style=False, sort_keys=True, allow_unicode=True)`, matching `build_sources_registry.py` exactly.
- `next_serial(registry)` returns `max(int(k) for k in registry) + 1` if registry non-empty, else `1`.
- `argparse` setup: one positional `csv_path` argument of type `Path`.
- `logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")` inside `main()`.
- `PDFS_DIR.mkdir(parents=True, exist_ok=True)` and `MARKDOWN_DIR.mkdir(...)` at the start of `main()`, before the CSV loop.

**Patterns to follow:**
- `scripts/build_sources_registry.py` — YAML read/write pattern.
- `scripts/ingest.py` — argparse + logging setup.

**Test scenarios:**
- `load_registry` on an existing `sources.yaml` returns the correct dict and URL set.
- `load_registry` on a missing file returns empty dict and empty set without raising.
- `load_registry` on an empty file returns empty dict/set.
- `write_registry` produces a YAML file whose keys sort correctly and all URL values are preserved.
- `next_serial({'038': ..., '001': ...})` returns `39`.
- `next_serial({})` returns `1`.

**Verification:**
- `uv run python scripts/harvest_sources.py --help` prints usage without error.
- A synthetic `sources.yaml` round-trips through `load_registry` → `write_registry` unchanged.

---

- [x] **Unit 2: URL classification — heuristics and HEAD fallback**

**Goal:** Implement `classify_url(url, client)` that returns `"pdf"`, `"web"`, or raises on truly unclassifiable cases (treated as web in practice).

**Requirements:** R4, R5

**Dependencies:** Unit 1

**Files:**
- Modify: `scripts/harvest_sources.py`
- Modify: `tests/test_harvest_sources.py`

**Approach:**
- `is_blank_or_invalid(url)`: returns True if `url` stripped is empty, or does not start with `http://` or `https://`.
- `heuristic_is_pdf(url)`: parse the URL path (`urllib.parse.urlparse(url).path`), apply checks in order — `.pdf` suffix (case-insensitive), `/download` anywhere in path, `/file` at end of path.
- `head_is_pdf(url, client)`: `client.head(url, follow_redirects=True, timeout=15.0)` → check `content-type` header contains `application/pdf`. Returns `False` on any `httpx.HTTPError` or `TimeoutException` (do not re-raise — classify as web).
- `classify_url(url, client)`: call `heuristic_is_pdf` first; if True, return `"pdf"`. Else call `head_is_pdf`; if True, return `"pdf"`. Else return `"web"`.
- `client` is an `httpx.Client` instance passed in (enables mocking in tests).

**Patterns to follow:**
- `scripts/extract.py` — httpx client configuration (User-Agent, follow_redirects, timeout).

**Test scenarios:**
- OFAC URL ending in `/download?inline=` → heuristic returns `"pdf"` (no HEAD needed).
- OFAC URL ending in `/download` (bare) → heuristic returns `"pdf"`.
- NCA URL ending in `/file` → heuristic returns `"pdf"`.
- `.pdf`-suffixed URL → heuristic returns `"pdf"`.
- Standard HTTPS page URL (no `.pdf`, no `/download`, no `/file`) → heuristic returns None → HEAD mock returns `text/html` → classify returns `"web"`.
- HEAD mock returns `application/pdf; charset=binary` → classify returns `"pdf"`.
- HEAD request raises `httpx.TimeoutException` → classify returns `"web"` without crashing.
- Blank string → `is_blank_or_invalid` returns True.
- `"not-a-url"` → `is_blank_or_invalid` returns True.

**Verification:**
- All test scenarios pass.
- No `requests` library imported; only `httpx` and `urllib.parse`.

---

- [x] **Unit 3: Fetch functions — PDF download and Jina web capture**

**Goal:** Implement `fetch_pdf(url, dest_path, client)` and `fetch_web(url, dest_path, client)` that retrieve content and write files.

**Requirements:** R6, R7, R9

**Dependencies:** Unit 1, Unit 2

**Files:**
- Modify: `scripts/harvest_sources.py`
- Modify: `tests/test_harvest_sources.py`

**Approach:**
- `fetch_pdf(url, dest_path, client)`:
  - `client.get(url, follow_redirects=True, timeout=60.0)` with browser User-Agent.
  - `response.raise_for_status()`.
  - `dest_path.write_bytes(response.content)`.
  - Returns number of bytes written.
  - Raises `httpx.HTTPError`, `httpx.TimeoutException`, or `OSError` on failure (caller handles).

- `fetch_web(url, dest_path, client)`:
  - Construct Jina Reader URL: `f"https://r.jina.ai/{url}"`.
  - `client.get(jina_url, follow_redirects=True, timeout=30.0)` with browser User-Agent.
  - `response.raise_for_status()`.
  - Check that `response.text` is non-empty (Jina may return an error body for blocked sites).
  - `dest_path.write_text(response.text, encoding="utf-8")`.
  - Returns character count written.
  - Raises on HTTP error, timeout, or empty response.

- Both functions are called with a pre-created `httpx.Client` instance from the main loop, so HTTP session is shared across all fetches.

**Patterns to follow:**
- `scripts/extract.py` lines 152–174 — httpx GET with User-Agent, follow_redirects, timeout, raise_for_status.
- `path.write_bytes()` for binary, `path.write_text(encoding="utf-8")` for text.

**Test scenarios:**
- `fetch_pdf` with a mocked client returns 200 and bytes content → file is written, byte count returned.
- `fetch_pdf` with a 403 response → `raise_for_status()` raises `httpx.HTTPStatusError`, which propagates to caller.
- `fetch_pdf` with a timeout → `httpx.TimeoutException` propagates to caller.
- `fetch_web` with a mocked Jina response → constructs the correct `r.jina.ai/` URL, writes text to file.
- `fetch_web` with empty response body → raises an appropriate error (empty markdown is not useful).
- `fetch_web` with a mocked 200 but Jina-style error page (contains "Error:") → implementation detail; decide at implementation time whether to detect this.

**Verification:**
- Unit tests cover success and failure paths for both fetch functions.
- No subprocess calls anywhere in the module.

---

- [x] **Unit 4: Main orchestration loop**

**Goal:** Wire Units 1–3 into the full CSV-iteration loop with dedup, serial assignment, error handling, and summary output.

**Requirements:** R1–R12 (integration of all)

**Dependencies:** Units 1, 2, 3

**Files:**
- Modify: `scripts/harvest_sources.py`
- Modify: `tests/test_harvest_sources.py`

**Approach:**
- Open the CSV with `csv.DictReader`. Guard: if `"Direct URL"` column not present, call `parser.error()` or `sys.exit(1)` with a clear message.
- Track counters: `pdf_count`, `web_count`, `skipped_count`, `failed_count`.
- For each row:
  1. `url = row["Direct URL"].strip()`
  2. If `is_blank_or_invalid(url)`: `LOGGER.warning("Skipping invalid URL: %r", url)`, `skipped_count += 1`, continue.
  3. If `url in existing_urls`: `LOGGER.info("Already registered, skipping: %s", url)`, `skipped_count += 1`, continue.
  4. `kind = classify_url(url, client)` — on HEAD exception, already handled internally (returns `"web"`).
  5. Determine `dest_path = PDFS_DIR / f"{serial:03d}.pdf"` or `MARKDOWN_DIR / f"{serial:03d}.md"`.
  6. Try fetch (`fetch_pdf` or `fetch_web`). On success: update `registry`, `existing_urls`, increment serial and the appropriate counter.
  7. On `Exception as exc`: `LOGGER.error("Failed %s: %s", url, exc)`, `failed_count += 1`, continue. Do **not** increment serial on failure.
- After the loop, `write_registry(registry, SOURCES_YAML)` in a `try/finally` block (so the registry is written even if an unexpected exception occurs mid-loop — though per-URL exceptions are caught).
- Final summary via `LOGGER.info(...)`:
  ```
  Harvest complete: %d PDFs, %d web pages, %d skipped, %d failed
  ```
- Use `httpx.Client(headers={"User-Agent": "..."}, follow_redirects=True)` as a context manager around the entire loop for connection reuse.

**Patterns to follow:**
- `scripts/ingest.py` — outer try/finally around the batch work.
- `scripts/build_sources_registry.py` — `for key, entry in sorted(registry.items()): print(...)` style summary (but use `LOGGER.info`, not `print()`).

**Test scenarios:**
- End-to-end with a 3-row test CSV: 1 PDF URL, 1 web URL, 1 already-in-registry URL.
  - Expected: 1 PDF file created, 1 markdown file created, 1 skipped, 0 failed.
  - `sources.yaml` gains exactly 2 new entries with the correct next keys.
- Idempotency: run the same CSV a second time → 3 skipped, 0 new files, `sources.yaml` unchanged.
- CSV with a missing `Direct URL` column → script exits with a clear error message, does not crash silently.
- A URL that returns HTTP 404 → logged as failed, not added to registry, serial not incremented; subsequent URLs still processed.
- A URL with a blank `Direct URL` field → skipped with a warning.
- Jina fetch returning empty text → logged as failed, markdown file not written.

**Verification:**
- `uv run python scripts/harvest_sources.py red_flag_sources/Global_AML_CFT_Sanctions_Red_Flag_Catalog.csv` runs without crashing.
- After a fresh run on the real CSV, `sources.yaml` has more entries than the initial 038.
- Re-running on the same CSV produces zero new entries and zero new files.
- The script exits with code 0 on normal completion (even if some URLs failed).

---

- [x] **Unit 5: Tests**

**Goal:** Ensure the test file is complete, all scenarios from Units 1–4 are covered, and the script is runnable without real network access in CI.

**Requirements:** All (verification layer)

**Dependencies:** Units 1–4

**Files:**
- Modify: `tests/test_harvest_sources.py`

**Approach:**
- Use `pytest` with `tmp_path` fixture for file system isolation.
- Use `unittest.mock.patch` or `pytest-mock` to mock `httpx.Client` and its methods (`get`, `head`) — do not make real network calls in tests.
- Structure tests around the public functions: `load_registry`, `write_registry`, `next_serial`, `is_blank_or_invalid`, `heuristic_is_pdf`, `head_is_pdf`, `classify_url`, `fetch_pdf`, `fetch_web`.
- One integration-style test for `main()` using a tmp CSV and mocked httpx.

**Patterns to follow:**
- `tests/` directory — existing test file style (pytest, no test classes unless warranted).

**Test scenarios:** (consolidate from Units 1–4 above)
- Heuristic detection: all known URL patterns in the catalog.
- HEAD fallback: mocked `Content-Type` responses.
- Fetch success and failure paths.
- Registry round-trip.
- Main loop: happy path, idempotency, per-URL failure isolation.

**Verification:**
- `uv run pytest tests/test_harvest_sources.py` passes with no real network calls.
- `uv run ruff check scripts/harvest_sources.py tests/test_harvest_sources.py` passes.
- `uv run mypy scripts/harvest_sources.py` passes (type annotations on all public functions).

## System-Wide Impact

- **Interaction graph:** `harvest_sources.py` reads `sources.yaml` and writes to it and to `red_flag_sources/pdfs/` and `red_flag_sources/markdown/`. `scripts/extract.py` reads from `red_flag_sources/pdf/` (note: extract.py references `red_flag_sources/pdf/` — verify the exact path at implementation time and align `PDFS_DIR` accordingly). `scripts/build_sources_registry.py` also writes `sources.yaml` — the two scripts must not run concurrently.
- **Error propagation:** Per-URL failures are caught and logged; they do not abort the loop. Fatal startup errors (missing CSV, unreadable sources.yaml) exit with code 1 via `sys.exit` or `parser.error()`.
- **State lifecycle risks:** If the script is interrupted before the final `write_registry` call, downloaded files exist on disk without corresponding registry entries. On next run, those URLs are re-fetched (overwriting files with identical content — safe).
- **API surface parity:** `sources.yaml` schema is URL-only — no new fields added. Existing consumers (`extract.py`, `build_sources_registry.py`) are unaffected.
- **Integration coverage:** A real-network smoke test (not in the automated suite) should be run once against a subset of the catalog CSV to validate that Jina Reader responses are non-empty and PDFs download as valid binary files.

## Risks & Dependencies

- **Jina Reader availability**: Some regulatory URLs may be blocked by Jina Reader (paywall, CAPTCHA, access control). These will produce either an HTTP error or a near-empty markdown response. The script logs them as failures; manual retrieval is the fallback.
- **OFAC `/download` heuristic false positives**: Any non-OFAC site that uses `/download` as a web-page route will be misclassified as PDF. The HEAD fallback corrects this, but only if the HEAD response clearly indicates `text/html`. Sites that redirect `/download` to a PDF may be double-classified correctly. Validate with the real CSV on first run.
- **Large PDF timeouts**: Some national risk assessment PDFs exceed 10 MB and may time out at 60s on slow government servers. Increase timeout via a future `--timeout-pdf` flag if needed.
- **`sources.yaml` concurrent modification**: If `build_sources_registry.py` is run while `harvest_sources.py` is active, registry entries may be overwritten. Document that the two scripts should not run simultaneously.
- **`extract.py` path alignment**: Check whether `extract.py` reads from `red_flag_sources/pdf/` (singular) or `red_flag_sources/pdfs/` (plural). Align `PDFS_DIR` to whichever path `extract.py` expects to avoid a gap in the pipeline.

## Documentation / Operational Notes

- Add `uv run python scripts/harvest_sources.py <csv-path>` to `CLAUDE.md`'s Commands section alongside the other script invocations.
- Add `red_flag_sources/pdfs/` and `red_flag_sources/markdown/` to `.gitignore` if they are not already excluded (raw regulatory downloads should not be committed).

## Sources & References

- **Origin document:** [docs/brainstorms/2026-05-10-csv-source-harvester-requirements.md](../brainstorms/2026-05-10-csv-source-harvester-requirements.md)
- Related code: `scripts/build_sources_registry.py`, `scripts/extract.py`, `scripts/ingest.py`
- Related data: `red_flag_sources/sources.yaml`, `red_flag_sources/Global_AML_CFT_Sanctions_Red_Flag_Catalog.csv`
- Jina Reader API: `https://r.jina.ai/{url}` (no authentication for public URLs)
