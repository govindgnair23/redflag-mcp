---
date: 2026-05-17
topic: unified-source-registry
---

# Unified Source Registry

## Problem Frame

Sources enter the project through multiple paths — PDFs downloaded directly (001–038 FinCEN series), web pages harvested via `harvest_sources.py`, and manually curated CSVs. There is no single file that answers "what sources have been extracted, which ones failed to download, and what's still missing?" The existing `.extracted_sources.yaml` tracks extraction events but has no document metadata. The catalog CSVs have metadata but no download or extraction status. The 001–038 FinCEN PDFs have neither. Failed downloads currently leave no trace.

## Workflow Context

```
Catalog CSVs (Global + Additional)  ←— curated source lists
    ↓ harvest_sources.py (download PDF / markdown)
    ↓ extract.py (LLM extraction → data/source/*.yaml)
    ↓ build_registry.py (combine catalog + downloaded files + YAMLs)
red_flag_sources/registry.csv        ←— unified ledger
```

The registry is a **derived artifact** regenerated on demand. The YAML files and catalog CSVs are the sources of truth.

## Requirements

- R1. A `build_registry.py` script generates `red_flag_sources/registry.csv` by combining three inputs: (a) catalog CSV rows, (b) downloaded files in `red_flag_sources/pdf/` and `red_flag_sources/markdown/`, and (c) extracted YAML files in `data/source/`.
- R2. Each row in the registry represents one source. It includes a `status` column with one of three values: `extracted`, `downloaded` (file exists but not yet extracted), or `not_downloaded` (in catalog but no file found).
- R3. Metadata columns include: `source_url`, `slug`, `document_title`, `regulator`, `jurisdiction`, `issued_date`, `primary_category`, `red_flag_count`, `output_file`, `extracted_at`. Columns are populated from catalog metadata where available, with YAML data filling gaps for extracted sources.
- R4. Catalog sources with no downloaded file appear as `not_downloaded` rows — a catalog-gap report embedded in the registry.
- R5. Sources extracted outside any catalog (the 001–038 FinCEN PDFs) appear as `extracted` rows with metadata derived entirely from their YAML files and the extraction manifest.
- R6. `primary_category` is the most frequently occurring category value across a source's YAML red flags.
- R7. Running the script regenerates the full registry from scratch. The CSV is not manually edited.

## Success Criteria

- `build_registry.py` produces a CSV covering all extracted sources, all downloaded-but-unextracted files, and all catalog sources that have no downloaded file.
- The 001–038 FinCEN PDFs appear as `extracted` rows even though they have no catalog entry.
- Catalog sources that failed to download appear as `not_downloaded`, making coverage gaps immediately visible.
- A new source extracted via `extract.py` appears in the registry after re-running the script, with no manual steps.

## Scope Boundaries

- The registry does not replace the Global catalog CSV as a curation and discovery tool.
- The registry does not drive the pipeline — `extract.py` continues to discover sources from directories.
- Merging the two existing catalog CSVs (`Global` + `Additional`) into one file is out of scope.
- `harvest_sources.py` is not changed to log failures; gap detection is done retroactively via file comparison.
- Richer metadata fields not in any YAML or catalog (Brief Summary, Target Audience) are populated from catalog when available and left blank otherwise.

## Key Decisions

- **Status via gap detection, not failure logging**: `harvest_sources.py` is unchanged; gaps are detected by comparing catalog URLs against downloaded files.
- **CSV format**: Chosen for human readability and auditability.
- **YAML-derived metadata for uncataloged sources**: The 001–038 PDFs use `regulatory_source`, `regulator`, `issued_date`, and `category` fields from their YAML files.
- **One row per source**: The registry is a source index, not a red flag index.

## Outstanding Questions

### Deferred to Planning

- [Affects R1][Technical] Should `build_registry.py` also deprecate `.extracted_sources.yaml` as the dedup mechanism for `extract.py`, or should both coexist until the registry is proven stable?
- [Affects R7][Technical] Should the script be wired into `extract.py` so the registry auto-updates after each extraction run, or remain a standalone command?
- [Affects R3][Needs research] Confirm `extracted_at` is reliably available for all sources including 001–038, either from `.extracted_sources.yaml` or YAML file mtime.
- [Affects R1][Needs research] Confirm how catalog URLs map to downloaded filenames (via `sources.yaml` serial key lookup) so gap detection can be implemented correctly.

## Next Steps

→ `/ce:plan` for structured implementation planning
