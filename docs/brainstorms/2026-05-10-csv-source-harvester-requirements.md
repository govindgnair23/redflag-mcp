---
date: 2026-05-10
topic: csv-source-harvester
---

# CSV Source Harvester

## Problem Frame

The Global AML/CFT/Sanctions Red Flag Catalog CSV (`red_flag_sources/Global_AML_CFT_Sanctions_Red_Flag_Catalog.csv`) lists ~218 authoritative regulatory documents from global bodies (FATF, FCA, EBA, MAS, AUSTRAC, NCA, etc.). The CSV has been updated so that most entries now point directly to individual documents rather than collection/index pages. The existing `pdflinks.txt` / `sources.yaml` pipeline covers only 38 FinCEN PDFs. There is no automated way to harvest the full catalog: download PDFs, fetch web pages as markdown, and register new entries in `sources.yaml` without duplicating existing entries.

The output of this script feeds the existing corpus build pipeline (`scripts/ingest.py` → `data/vectors/`).

## Requirements

- R1. The script accepts a CSV file path as its single positional argument (e.g., `uv run python scripts/harvest_sources.py red_flag_sources/Global_AML_CFT_Sanctions_Red_Flag_Catalog.csv`).
- R2. It reads the `Direct URL` column from each row of the CSV.
- R3. URLs already present as a value in `red_flag_sources/sources.yaml` are skipped (deduplication). `sources.yaml` is the authoritative registry.
- R4. Empty, blank, or malformed URLs are skipped with a warning to stderr.
- R5. For each new URL, the script determines whether it is a PDF via a two-step check: (a) static heuristics — URL path ends with `.pdf` (case-insensitive), or URL contains `/download` in the path (covers OFAC patterns such as `?inline`, `?inline=`, and bare `/download`), or URL path ends with `/file` (covers NCA-style download links); (b) if heuristics are inconclusive, make an HTTP HEAD request and inspect the `Content-Type` response header for `application/pdf`.
- R6. PDF URLs are downloaded to `red_flag_sources/pdfs/NNN.pdf`, where `NNN` is the next sequential three-digit key continuing from the current maximum key in `sources.yaml`.
- R7. All other URLs are fetched via `curl -s https://r.jina.ai/{url}` and the returned markdown is written to `red_flag_sources/markdown/NNN.md`.
- R8. Each successfully harvested URL is appended to `sources.yaml` with its assigned key and URL. The schema stays unchanged: `{key: {url: ...}}`.
- R9. URLs that fail (HTTP error, timeout, curl non-zero exit, empty response) are skipped with an error logged to stderr; the script does not crash.
- R10. The script is idempotent: re-running against the same CSV only processes URLs absent from `sources.yaml` at the time of execution.
- R11. The script prints a summary on completion: N PDFs downloaded, M web pages fetched, K skipped (already in registry), J failed.
- R12. The output directories `red_flag_sources/pdfs/` and `red_flag_sources/markdown/` are created automatically if they do not exist.

## Success Criteria

- Running the script against the full catalog CSV results in every reachable URL being either downloaded as a PDF or captured as markdown, with all new entries registered in `sources.yaml`.
- Re-running the script produces zero new downloads and zero new registry entries (all already present).
- URLs already in `sources.yaml` from the existing FinCEN corpus (keys 001-038) are not re-fetched.
- A failed URL (404, timeout) does not abort the run; the script continues and reports the failure in the final summary.
- The `red_flag_sources/pdfs/` and `red_flag_sources/markdown/` folders exist and contain files named `NNN.pdf` / `NNN.md` matching their keys in `sources.yaml`.

## Scope Boundaries

- The script does not parse or extract content from PDFs or markdown — that is `scripts/ingest.py`'s job.
- The script does not follow links embedded inside fetched web pages (no recursive crawl). The updated CSV has already flattened most collection pages to direct document links; the remaining web-page entries (e.g. FATF landing pages, ACIP portal, EBA homepage) are fetched as-is.
- The script does not modify `red_flag_sources/pdflinks.txt` — that file remains the hand-curated FinCEN-only list.
- The script does not add metadata fields (title, region, type) to `sources.yaml` entries — schema stays URL-only.
- The script does not check redistribution rights before downloading; that remains a maintainer responsibility per R27 of the corpus brainstorm.
- Rate limiting / politeness delays between requests are out of scope for the first version but should not be architected out.

## Key Decisions

- **Output location**: `red_flag_sources/pdfs/` and `red_flag_sources/markdown/` — co-located with `sources.yaml` and `pdflinks.txt`. All raw source material stays in one place.
- **Sequential numbering, mixed types**: New entries continue from the current max key in `sources.yaml` (currently 038). PDFs and web pages share one counter. Simplest registry management.
- **sources.yaml schema unchanged**: URL-only entries. Type is derivable from file extension on disk at lookup time.
- **Jina Reader via curl**: `curl -s https://r.jina.ai/{url}` — no local Jina install required, no API key needed for standard use.
- **Heuristic-first PDF detection**: Static URL heuristics cover the known patterns in this catalog — `.pdf` suffix, OFAC `/download` variants (`?inline`, `?inline=`, bare), and NCA `/file` links. HEAD request is the fallback for anything not matched by heuristics.
- **Idempotency via sources.yaml**: The registry is the dedup ground truth. No separate state file needed.

## Dependencies / Assumptions

- `curl` is available on the execution machine.
- `red_flag_sources/sources.yaml` exists and is readable; the script reads it before processing any URLs.
- The CSV column name is exactly `Direct URL` (as it appears in the catalog).
- The Jina Reader API (`r.jina.ai`) is publicly accessible without authentication for most regulatory URLs.
- Some URLs may be paywalled, require institutional access, or return a Jina error page rather than document content — treated as failures.

## Outstanding Questions

### Deferred to Planning

- [Affects R5][Technical] Should the `/download` heuristic be scoped more tightly (e.g. only when the host is `ofac.treasury.gov` or `*.gov`) to avoid false-positives on other sites that use `/download` as a web-page route?
- [Affects R6, R7][Technical] Should the file naming use `NNN.pdf`/`NNN.md` (key-only) or `NNN_slug.pdf`/`NNN_slug.md` (key + title slug from CSV)? Key-only is simpler; slug aids human browsing.
- [Affects R9][Technical] What request timeout is appropriate for large regulatory PDFs (some are 10+ MB)?
- [Affects R11][Needs research] Should the Jina CLI call include any headers (e.g., `Accept: text/markdown`) or is the default sufficient?

## Next Steps

-> /ce:plan for structured implementation planning
