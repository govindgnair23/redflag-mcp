---
title: "feat: Build unified source registry"
type: feat
status: active
date: 2026-05-17
origin: docs/brainstorms/2026-05-17-unified-source-registry-requirements.md
---

# Build Unified Source Registry

## Overview

Create `scripts/build_registry.py` that generates `red_flag_sources/registry.csv` — a single ledger covering every source in the project: extracted, downloaded-but-unextracted, and catalog-only (not downloaded). The registry is a derived artifact regenerated from scratch on each run.

## Problem Frame

Sources enter the project through multiple paths — FinCEN PDFs (001–038), harvested web pages via `harvest_sources.py`, and manually curated catalog CSVs. No single file answers "what sources have been extracted, which failed to download, and what's still missing?" (see origin: `docs/brainstorms/2026-05-17-unified-source-registry-requirements.md`)

## Requirements Trace

- R1. `build_registry.py` combines three inputs: catalog CSVs, downloaded files, and extracted YAMLs
- R2. Each row has a `status`: `extracted`, `downloaded`, or `not_downloaded`
- R3. Metadata columns: `source_url`, `slug`, `document_title`, `regulator`, `jurisdiction`, `issued_date`, `primary_category`, `red_flag_count`, `output_file`, `extracted_at`
- R4. Catalog sources with no downloaded file appear as `not_downloaded`
- R5. Sources extracted outside any catalog (001–038 FinCEN PDFs) appear as `extracted` with YAML-derived metadata
- R6. `primary_category` is the most frequent category across a source's red flags
- R7. Running the script regenerates the full registry from scratch

## Scope Boundaries

- Does not replace Global catalog CSV as a curation tool
- Does not drive the pipeline — `extract.py` continues to discover from directories
- Merging the two catalog CSVs is out of scope
- `harvest_sources.py` is unchanged — gap detection is retroactive
- `.extracted_sources.yaml` coexists with the registry (no deprecation)

## Context & Research

### Relevant Code and Patterns

- `red_flag_sources/sources.yaml` — serial-key → URL mapping (~200 entries); only successful downloads registered. Key for gap detection: catalog URL present in `sources.yaml` values → downloaded; absent → `not_downloaded`
- `data/source/.extracted_sources.yaml` — 40+ entries with `source`, `slug`, `output_file`, `extracted_at`. Confirmed available for all sources including 001–038
- `data/source/*.yaml` — 40 extracted YAML files, each a list of red flag dicts with `regulatory_source`, `regulator`, `regulator_jurisdiction`, `issued_date`, `category`, `source_url`
- `red_flag_sources/Global_AML_CFT_Sanctions_Red_Flag_Catalog.csv` — 219 rows with columns: Region, Country/Jurisdiction, Issuing Body, Document Title, Document Type, Year/Date Published, Primary Topic, Brief Summary, Direct URL, Target Audience
- `red_flag_sources/Additional_sources_05132026.csv` — same schema, 2 rows
- `scripts/harvest_sources.py` — assigns serial numbers, downloads to `pdf/` and `markdown/`, registers in `sources.yaml`
- `scripts/extract.py` — processes PDFs and markdowns, writes YAMLs and `.extracted_sources.yaml`

### Institutional Learnings

- Serial keys are the join key across subsystems (filenames, `sources.yaml`, YAML IDs like `207-01`)
- `sources.yaml` is the Rosetta Stone: `serial_key` → `url`
- Failed downloads leave no trace in `sources.yaml`, enabling gap detection by absence

## Key Technical Decisions

- **Gap detection via `sources.yaml` absence**: Compare catalog `Direct URL` values against URLs in `sources.yaml`. Missing = `not_downloaded`. No failure logging needed.
- **CSV output format**: Human-readable, auditable, diffable in git.
- **YAML-first metadata for uncataloged sources**: 001–038 PDFs use `regulatory_source`, `regulator`, `issued_date`, `category` from their YAML red flags.
- **`primary_category` via mode**: Count `category` values across all red flags in a YAML, take the most frequent.
- **Standalone script**: Not wired into `extract.py`. Run manually after extraction.
- **Coexistence with `.extracted_sources.yaml`**: Registry does not replace the dedup mechanism.

## Open Questions

### Resolved During Planning

- **`extracted_at` availability**: Confirmed present for all 40+ sources in `.extracted_sources.yaml`, including 001–038 FinCEN PDFs.
- **Catalog URL → filename mapping**: `sources.yaml` maps serial keys to URLs. Gap detection compares catalog URLs against the set of URLs in `sources.yaml` values.
- **Deprecating `.extracted_sources.yaml`**: No — both coexist until registry is proven stable.
- **Auto-update after extraction**: No — `build_registry.py` stays standalone.

### Deferred to Implementation

- **URL normalization**: Catalog URLs may have trailing slashes or minor differences from `sources.yaml` URLs. Handle with basic normalization (strip trailing slash) and refine if mismatches appear.

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification. The implementing agent should treat it as context, not code to reproduce.*

```
build_registry.py

1. Load catalog CSVs → list of {url, title, regulator, jurisdiction, ...}
2. Load sources.yaml → dict of {serial_key: url}
3. Load .extracted_sources.yaml → dict of {output_file: extracted_at}
4. Scan data/source/*.yaml → for each file:
     - Read red flags, derive: regulatory_source, regulator, jurisdiction,
       issued_date, source_url, primary_category (mode of category),
       red_flag_count (len)
     - Look up extracted_at from step 3
     - Status = "extracted"
5. For each catalog URL:
     - If URL found in sources.yaml values AND matching YAML exists → skip (already in step 4)
     - If URL found in sources.yaml values but NO YAML → status = "downloaded"
     - If URL NOT in sources.yaml values → status = "not_downloaded"
6. Merge: extracted rows (step 4) + downloaded rows (step 5) + not_downloaded rows (step 5)
7. Write registry.csv sorted by status then slug/title
```

## Implementation Units

- [x] **Unit 1: Core data loading functions**

  **Goal:** Build the three data-loading functions that read catalog CSVs, `sources.yaml`, and `.extracted_sources.yaml`.

  **Requirements:** R1

  **Dependencies:** None

  **Files:**
  - Create: `scripts/build_registry.py`
  - Test: `tests/test_build_registry.py`

  **Approach:**
  - `load_catalogs(catalog_paths: list[Path]) -> list[dict]` — read each CSV with `csv.DictReader`, normalize the `Direct URL` column (strip whitespace/trailing slash), return list of row dicts
  - `load_sources_yaml(path: Path) -> dict[str, str]` — parse YAML, return `{serial_key: url}` mapping
  - `load_extraction_manifest(path: Path) -> dict[str, str]` — parse `.extracted_sources.yaml`, return `{output_file: extracted_at}` mapping keyed by output filename (e.g., `data/source/207.yaml`)

  **Patterns to follow:**
  - YAML loading pattern from `scripts/extract.py` (uses `yaml.safe_load`)
  - CSV reading pattern from `scripts/review_markdown_sources.py`

  **Test scenarios:**
  - Load a minimal catalog CSV with 2 rows, verify URL normalization
  - Load a minimal `sources.yaml`, verify serial-key lookup
  - Load a minimal `.extracted_sources.yaml`, verify `extracted_at` keyed by output file
  - Handle missing files gracefully (empty list/dict)

  **Verification:**
  - All three loaders return correct data structures from fixture files

- [x] **Unit 2: YAML metadata extraction and primary_category derivation**

  **Goal:** Scan `data/source/*.yaml` files and derive per-source metadata rows with status `extracted`.

  **Requirements:** R3, R5, R6

  **Dependencies:** Unit 1 (needs extraction manifest for `extracted_at`)

  **Files:**
  - Modify: `scripts/build_registry.py`
  - Test: `tests/test_build_registry.py`

  **Approach:**
  - `build_extracted_rows(yaml_dir: Path, manifest: dict) -> list[dict]` — glob `*.yaml` (excluding `.extracted_sources.yaml`), for each file:
    - Load red flags list
    - Take metadata from first red flag: `regulatory_source` → `document_title`, `regulator`, `regulator_jurisdiction` → `jurisdiction`, `issued_date`, `source_url`
    - `red_flag_count` = `len(flags)`
    - `primary_category` = most common `category` value (use `collections.Counter.most_common(1)`)
    - `slug` = filename stem
    - `output_file` = relative path (`data/source/<name>.yaml`)
    - `extracted_at` from manifest lookup
    - `status` = `"extracted"`

  **Patterns to follow:**
  - YAML structure visible in `data/source/207.yaml` — list of dicts with consistent field names

  **Test scenarios:**
  - YAML with 5 red flags, 3 `sanctions_evasion` + 2 `layering` → `primary_category` = `sanctions_evasion`
  - YAML with single red flag → category is that flag's category
  - YAML not in manifest → `extracted_at` is empty string
  - Files starting with `.` are excluded from glob

  **Verification:**
  - Running against a test YAML produces a dict with all R3 columns populated

- [x] **Unit 3: Status derivation and catalog gap detection**

  **Goal:** Determine `downloaded` and `not_downloaded` rows by comparing catalog URLs against `sources.yaml`.

  **Requirements:** R2, R4

  **Dependencies:** Unit 1, Unit 2

  **Files:**
  - Modify: `scripts/build_registry.py`
  - Test: `tests/test_build_registry.py`

  **Approach:**
  - `build_catalog_rows(catalogs: list[dict], sources_yaml: dict, extracted_urls: set) -> list[dict]`
    - Build `url_set` from `sources_yaml` values (normalize URLs)
    - Build `extracted_urls` from Unit 2 output (set of source_urls already covered)
    - For each catalog row:
      - If URL in `extracted_urls` → skip (already an `extracted` row)
      - If URL in `url_set` → `status = "downloaded"`, populate metadata from catalog columns
      - Else → `status = "not_downloaded"`, populate metadata from catalog columns
    - Map catalog columns to registry columns: `Document Title` → `document_title`, `Issuing Body` → `regulator`, `Country/Jurisdiction` → `jurisdiction`, `Direct URL` → `source_url`, `Year/Date Published` → `issued_date`, `Primary Topic` → `primary_category`

  **Test scenarios:**
  - Catalog URL present in `sources.yaml` AND in extracted set → excluded (no duplicate)
  - Catalog URL present in `sources.yaml` but NOT extracted → `downloaded`
  - Catalog URL absent from `sources.yaml` → `not_downloaded`
  - URL normalization: trailing slash stripped before comparison

  **Verification:**
  - A 3-row catalog with one extracted, one downloaded, one missing produces exactly 2 rows (downloaded + not_downloaded)

- [x] **Unit 4: Registry assembly and CSV output**

  **Goal:** Merge all rows and write `red_flag_sources/registry.csv`.

  **Requirements:** R1, R7

  **Dependencies:** Units 1–3

  **Files:**
  - Modify: `scripts/build_registry.py`
  - Test: `tests/test_build_registry.py`

  **Approach:**
  - `build_registry()` — orchestrator function:
    - Call loaders (Unit 1)
    - Call `build_extracted_rows` (Unit 2)
    - Call `build_catalog_rows` (Unit 3)
    - Merge lists, sort by `status` (extracted → downloaded → not_downloaded) then `slug`/`document_title`
    - Write with `csv.DictWriter` to `red_flag_sources/registry.csv`
  - Column order: `status`, `slug`, `document_title`, `regulator`, `jurisdiction`, `issued_date`, `source_url`, `primary_category`, `red_flag_count`, `output_file`, `extracted_at`
  - Add `__main__` block with `argparse` (no required args — all paths are constants)

  **Patterns to follow:**
  - Script structure from `scripts/extract.py` — `PROJECT_ROOT` constant, `__main__` block
  - Use `pathlib.Path` for all paths

  **Test scenarios:**
  - Full integration: 2 extracted YAMLs + 3 catalog rows (1 extracted overlap, 1 downloaded, 1 not_downloaded) → CSV with 4 rows
  - CSV columns match expected order
  - Regeneration: running twice produces identical output

  **Verification:**
  - `uv run python scripts/build_registry.py` produces `red_flag_sources/registry.csv`
  - CSV contains rows for all extracted sources, downloaded-but-unextracted files, and not-downloaded catalog entries
  - 001–038 FinCEN PDFs appear as `extracted` even though they have no catalog entry

## System-Wide Impact

- **Interaction graph:** No callbacks or middleware affected. The script is read-only against existing data files.
- **Error propagation:** Script should exit with non-zero status if critical input files (`sources.yaml`, `.extracted_sources.yaml`) are missing.
- **State lifecycle risks:** None — registry is regenerated from scratch each run, never manually edited.
- **API surface parity:** No other interfaces affected.
- **Integration coverage:** End-to-end test with real project data (running the script and checking output) is the primary validation.

## Risks & Dependencies

- **URL normalization mismatches:** Catalog URLs and `sources.yaml` URLs may differ in minor ways (trailing slashes, http vs https, URL encoding). Mitigate with basic normalization; refine if mismatches appear in practice.
- **YAML schema drift:** If future YAML files change field names (e.g., `regulator` → `issuing_body`), the registry builder will silently produce empty cells. Mitigate by validating that key fields are non-empty in extracted rows and logging warnings.

## Sources & References

- **Origin document:** [docs/brainstorms/2026-05-17-unified-source-registry-requirements.md](docs/brainstorms/2026-05-17-unified-source-registry-requirements.md)
- Related code: `scripts/extract.py`, `scripts/harvest_sources.py`
- Data files: `red_flag_sources/sources.yaml`, `data/source/.extracted_sources.yaml`, `data/source/*.yaml`
- Catalog files: `red_flag_sources/Global_AML_CFT_Sanctions_Red_Flag_Catalog.csv`, `red_flag_sources/Additional_sources_05132026.csv`
