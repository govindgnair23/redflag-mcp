# redflag-mcp

MCP server exposing AML red flag knowledge as queryable tools. Compliance officers ask natural-language questions; the server returns relevant, sourced red flags from either a local LanceDB vector store or a packaged SQLite FTS5 corpus.

## Hosted Connector

Public users should start with the hosted MCP URL:

```text
https://<deployment>/mcp
```

Add that URL in a hosted MCP client, enable the connector, and ask AML red flag research questions such as:

```text
What red flags apply to TBML invoice mismatch?
Which red flags cover bulk cash movement to Mexico?
List source coverage for the corpus.
```

Public hosted mode is not for confidential customer, transaction, institution, or investigation details. User prompts are sent to the hosted MCP service operator and the host client. Use local desktop or institution-hosted deployments for sensitive institution-specific context.

The hosted connector is backed by a verified packaged corpus. End users do not need Python, repository setup, package downloads, ingestion, OpenAI keys, or environment variables. Operators should use [docs/hosted-deployment.md](docs/hosted-deployment.md) for Railway deployment, corpus activation, rollback, logging, and validation.

## Overview

Six distinct workflows:

1. **Source harvesting** — download PDFs and capture web pages from the AML catalog CSV into the local source registry
2. **Extraction** — pull AML red flags out of PDFs or web pages using an LLM and save them as YAML
3. **Ingestion** — embed the YAML files and load them into the local vector database
4. **Corpus packaging** — build a versioned SQLite FTS5 package for offline lexical runtime use
5. **Hosted deployment** — run the ASGI MCP service from a verified corpus package at one public `/mcp` URL
6. **Query** — MCP server answers search and filtering requests against the configured local or hosted store

---

## Source Harvesting

`scripts/harvest_sources.py` automates acquisition of regulatory documents from the Global AML/CFT/Sanctions Red Flag Catalog. It reads the `Direct URL` column, classifies each URL as a PDF or web page, downloads the file, and registers it in `red_flag_sources/sources.yaml`.

```bash
uv run python scripts/harvest_sources.py red_flag_sources/Global_AML_CFT_Sanctions_Red_Flag_Catalog.csv
```

**What it does:**

1. Reads the `Direct URL` column from each CSV row
2. Skips blank, malformed, or already-registered URLs
3. Classifies the URL as PDF via path heuristics (`.pdf` suffix, `/download`, `/file`) — falls back to an HTTP HEAD check for ambiguous cases
4. Downloads PDFs to `red_flag_sources/pdf/NNN.pdf`
5. Fetches web pages via the [Jina Reader API](https://r.jina.ai/) and saves cleaned markdown to `red_flag_sources/markdown/NNN.md`
6. Appends each new entry to `sources.yaml` (written once at the end)
7. Prints a final summary: PDFs downloaded, web pages fetched, skipped, failed

The script is **idempotent** — re-running against the same CSV produces no new files or registry entries. Per-URL failures are logged and skipped without aborting the run.

```
red_flag_sources/
  Global_AML_CFT_Sanctions_Red_Flag_Catalog.csv   # input catalog (~218 URLs)
  sources.yaml                                      # registry of all harvested URLs
  pdf/                                              # downloaded PDFs (gitignored via *.pdf)
  markdown/                                         # Jina Reader captures (gitignored)
```

After harvesting, pass the downloaded files to the extraction pipeline:

```bash
# Extract red flags from all newly downloaded PDFs
uv run python scripts/extract.py --parallel

# Or target a specific serial range
uv run python scripts/extract.py --range 039-060 --parallel
```

> **Note:** `sources.yaml` is the shared registry for both `harvest_sources.py` and `build_sources_registry.py`. Do not run both scripts concurrently — each does a full overwrite on save.

---

## Extraction Pipeline

`scripts/extract.py` takes a regulatory document (PDF file or URL), sends its text to an OpenAI model, and writes a structured YAML file into `data/source/`. Each extracted entry includes a `source_url` linking back to the original document.

### Prerequisites

```bash
uv sync --extra dev
export OPENAI_API_KEY=sk-...
```

### Adding PDFs in bulk (recommended workflow)

**Step-by-step:**

1. **Add the source URL to `red_flag_sources/pdflinks.txt`** — one URL per line, in serial order. Line 1 → key `001`, line 2 → `002`, etc.
2. **Download the PDF** and save it to `red_flag_sources/pdf/` named `NNN_short_descriptive_name.pdf`, where `NNN` matches its line position in `pdflinks.txt`.
3. **Regenerate the registry:** `uv run python scripts/build_sources_registry.py`
4. **Run extraction:** `uv run python scripts/extract.py --parallel`

> **Key constraint:** the `NNN_` prefix in the filename must match the line number in `pdflinks.txt`. Line 1 = `001_*.pdf`, line 2 = `002_*.pdf`, etc. This is how the extractor links each PDF to its public source URL.

---

PDFs are stored in `red_flag_sources/pdf/` and must be named with a zero-padded serial prefix:

```
red_flag_sources/pdf/
  001_fincen_alert_russian_sanctions_evasion.pdf
  002_ffiec_bsa_aml_examination_manual.pdf
  003_fatf_guidance_virtual_assets.pdf
```

Each serial number maps to a public URL for the source document. Maintain this mapping in `red_flag_sources/pdflinks.txt` — one URL per line, in serial order:

```
# FinCEN Russian Sanctions Evasion Alert
https://fincen.gov/sites/default/files/2022-06/Alert%20FIN-2022-Alert001_508C.pdf

# FFIEC BSA/AML Examination Manual
https://bsaaml.ffiec.gov/manual

# FATF Guidance on Virtual Assets
https://www.fatf-gafi.org/...
```

Blank lines and lines starting with `#` are ignored. After editing `pdflinks.txt`, regenerate `sources.yaml`:

```bash
uv run python scripts/build_sources_registry.py
```

Then run batch extraction:

```bash
uv run python scripts/extract.py --parallel
```

Only new (unprocessed) PDFs are extracted — previously processed sources are skipped automatically.

### Batch extraction commands

```bash
# Sequential batch
uv run python scripts/extract.py

# Parallel batch (4 workers by default)
uv run python scripts/extract.py --parallel

# Parallel batch with custom worker count
uv run python scripts/extract.py --parallel 8

# Force re-extract everything
uv run python scripts/extract.py --force --parallel

# Process only PDFs in a serial range (e.g. 001 through 005)
uv run python scripts/extract.py --range 001-005

# Range + parallel
uv run python scripts/extract.py --range 001-005 --parallel

# Force re-extract a range
uv run python scripts/extract.py --force --range 001-005 --parallel
```

> **Note:** `--range` applies only to numbered PDFs. Web URLs in `Weblinks.md` are excluded when a range is active.

### Single source (ad hoc)

```bash
# Extract from a local PDF
uv run python scripts/extract.py red_flag_sources/pdf/001_fincen_alert.pdf

# Extract from a URL
uv run python scripts/extract.py https://example.com/regulatory-guidance

# Re-extract a source that was already processed
uv run python scripts/extract.py --force red_flag_sources/pdf/001_fincen_alert.pdf
```

For single-source PDFs, add the URL to `pdflinks.txt` and run `build_sources_registry.py` first so the extractor can populate `source_url` in the output.

### What it does

1. **Fetches the document** — downloads the web page (strips nav/footer/scripts) or reads text from the PDF via pdfplumber
2. **Sends to OpenAI** — prompts `gpt-4o-mini` (override with `OPENAI_EXTRACTION_MODEL`) to extract every distinct AML red flag indicator as structured JSON
3. **Validates** — each returned flag is checked against the `RedFlagSource` schema; invalid entries are skipped with a warning
4. **Writes YAML** — saves to `data/source/<slug>.yaml`, one entry per red flag
5. **Updates the manifest** — records the source in `data/source/.extracted_sources.yaml` to prevent re-processing

### Output schema

Each entry in the YAML file has the following fields:

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | string | yes | Unique identifier, e.g. `001-fincen-alert-01` |
| `description` | string | yes | Standalone description of the red flag indicator |
| `source_url` | string | no | Public URL of the source document |
| `product_types` | list[string] | no | Financial products this applies to (e.g. `depository`, `crypto`, `msb`) |
| `industry_types` | list[string] | no | Customer industries or sectors this applies to (e.g. `oil_and_gas`, `government_benefits`) |
| `customer_profiles` | list[string] | no | Customer archetypes this applies to (e.g. `small_business`, `charity_or_nonprofit`) |
| `geographic_footprints` | list[string] | no | Relevant geographies or corridors (e.g. `southwest_border`, `mexico`) |
| `regulatory_source` | string | no | Source document name or authority (e.g. `FinCEN Alert FIN-2022-Alert001`) |
| `regulator` | string | no | Abbreviated issuing authority (e.g. `FinCEN`, `OFAC`, `FATF`). Populated at extraction; auto-tagged by write-back when absent. |
| `regulator_jurisdiction` | string | no | Canonical jurisdiction code deterministically derived from `regulator` (e.g. `US`, `FR`, `SG`, `AU`, `GB`, `EU`). Not normally extracted by the LLM. |
| `issued_date` | string | no | Publication date of the source document (ISO 8601: YYYY-MM-DD, YYYY-MM, or YYYY). |
| `risk_level` | string | no | `high`, `medium`, or `low` |
| `category` | string | no | AML typology (e.g. `structuring`, `sanctions_evasion`, `shell_company`) |
| `simulation_type` | string | no | Optional simulation complexity code (e.g. `1A`, `2B`) |
| `typology_family` | list[string] | no | Higher-level AML typology families (e.g. `trade_based_money_laundering`, `fraud_proceeds`) |
| `transaction_patterns` | list[string] | no | Observable behavioral patterns (e.g. `structuring`, `trade_document_manipulation`) |
| `key_terms` | list[string] | no | Short searchable phrases, instruments, thresholds, or acronyms (e.g. `TBML`, `CTR`, `cashier's check`) |

`regulator` and `issued_date` are requested during extraction. `regulator_jurisdiction` is derived in code from `regulator`; if the regulator is missing or unmapped, it stays unset and ingestion logs a warning. `typology_family`, `transaction_patterns`, and `key_terms` are added to existing YAML source files by running `scripts/ingest.py --write-back-yaml` (see [Enriching YAML source files](#enriching-yaml-source-files-write-back) below).

### Deduplication

`data/source/.extracted_sources.yaml` tracks every processed source by its canonical path or URL. Sources already in the manifest are skipped in both batch and single-source mode. Use `--force` to re-extract a source regardless.

---

## Ingestion

After extraction, embed the YAML files and load them into the vector database:

```bash
uv run python scripts/ingest.py
```

For the initial local corpus, ingest only the three target files:

```bash
uv run python scripts/ingest.py \
  data/source/001_federal_child_nutrition_fraud.yaml \
  data/source/002_oil_smuggling_cartels.yaml \
  data/source/003_bulk_cash_smuggling_repatriation.yaml
```

This generates embeddings with `nomic-embed-text-v1.5` and upserts records into LanceDB at `data/vectors/`. Run ingestion before connecting the MCP server to a desktop client; the embedding model downloads on first use and is better cached during ingestion than during server startup.

`OPENAI_API_KEY` is optional for ingestion. When it is set, ingestion can auto-tag missing metadata into the derived LanceDB records. When it is not set, ingestion preserves available YAML metadata and leaves missing rich consultation fields empty. Source YAML files are not rewritten by normal ingestion.

### Enriching YAML source files (write-back)

To enrich source YAML files with `typology_family`, `transaction_patterns`, `key_terms`, `regulator`, `regulator_jurisdiction`, and `issued_date` — fields used for offline keyword search and faceted filtering — run ingestion with `--write-back-yaml`:

```bash
export OPENAI_API_KEY=sk-...
uv run python scripts/ingest.py --write-back-yaml data/source/001_federal_child_nutrition_fraud.yaml
```

Write-back supports the same batch selection styles as extraction:

```bash
# All visible YAML files in data/source/
uv run python scripts/ingest.py --write-back-yaml

# Multiple explicit YAML files
uv run python scripts/ingest.py --write-back-yaml \
  data/source/001_federal_child_nutrition_fraud.yaml \
  data/source/002_oil_smuggling_cartels.yaml

# Serial range by source filename prefix
uv run python scripts/ingest.py --write-back-yaml --range 001-003

# Parallel file-level write-back (4 workers by default, or pass a count)
uv run python scripts/ingest.py --write-back-yaml --range 001-003 --parallel
uv run python scripts/ingest.py --write-back-yaml --parallel 8
```

This enriches each selected source file in-place and exits without updating the vector database. Existing metadata is not overwritten by the LLM; only missing fields are requested, and deterministic fields such as `regulator_jurisdiction` are derived in code. After write-back, re-run normal ingestion to load the enriched records:

```bash
uv run python scripts/ingest.py data/source/001_federal_child_nutrition_fraud.yaml
```

> **Note:** If you deploy this change against an existing `data/vectors/` store, delete the store and re-ingest from scratch so the new columns (`typology_family`, `transaction_patterns`, `key_terms`, `regulator`, `regulator_jurisdiction`, `issued_date`) are present in the LanceDB schema:
> ```bash
> rm -rf data/vectors/
> uv run python scripts/ingest.py
> ```

---

## Corpus Packaging

Maintainers can build a versioned, verifiable SQLite FTS5 corpus package from approved YAML records:

```bash
uv run python scripts/build_corpus.py \
  --output-dir dist/corpus \
  --version 2026.04.29 \
  --all-sources

# Or build a curated corpus from explicit YAML files
uv run python scripts/build_corpus.py \
  --output-dir dist/corpus \
  --version 2026.04.29 \
  data/source/001_federal_child_nutrition_fraud.yaml \
  data/source/002_oil_smuggling_cartels.yaml \
  data/source/003_bulk_cash_smuggling_repatriation.yaml

uv run python scripts/verify_corpus.py dist/corpus/redflag-corpus-2026.04.29.zip
```

The package contains `manifest.json` and `redflags.sqlite`. The manifest records schema version, build timestamp, source record hashes, file hashes, record/source counts, and source redistribution metadata. Source documents are treated as URL-only unless `data/lexicon/source_metadata.yaml` explicitly clears them for bundling.

The current SQLite lexical corpus schema version is `3`. Rebuild older corpus packages after schema changes that add stored fields or filters.

Run the hosted retrieval smoke benchmark before publishing a corpus package:

```bash
uv run python scripts/evaluate_retrieval.py \
  --corpus dist/corpus/redflag-corpus-2026.04.29.zip \
  --benchmark data/eval/hosted_retrieval_queries.yaml
```

This benchmark checks representative alias, geography, typology, product/channel, and source-specific queries against the lexical corpus. It is a launch gate, not proof of broad AML retrieval quality.

### Running from a corpus

The server can run directly against a built SQLite corpus without loading the embedding model:

```bash
REDFLAG_CORPUS_PATH=dist/corpus/redflags.sqlite uv run python -m redflag_mcp
```

It can also verify and install a ZIP package into a local corpus cache:

```bash
REDFLAG_CORPUS_PACKAGE=dist/corpus/redflag-corpus-2026.04.29.zip \
REDFLAG_CORPUS_CACHE_DIR=~/.redflag-mcp \
uv run python -m redflag_mcp
```

For release-index driven activation:

```bash
REDFLAG_CORPUS_RELEASE_INDEX=dist/corpus/releases.json \
REDFLAG_CORPUS_VERSION=2026.04.29 \
REDFLAG_CORPUS_CACHE_DIR=~/.redflag-mcp \
uv run python -m redflag_mcp
```

Set `REDFLAG_CORPUS_AUTO_UPDATE=0` to reuse the active cached corpus without checking the package or release index. When no corpus environment variables are set, the server falls back to the LanceDB vector store at `data/vectors/`.

---

## MCP Server

```bash
# Start server (stdio mode, for Claude Desktop / Claude Code)
uv run python -m redflag_mcp

# Start in MCP inspector
uv run mcp dev src/redflag_mcp/server.py

# Start as HTTP server (for OpenAI agents or other HTTP clients)
MCP_TRANSPORT=http MCP_HOST=0.0.0.0 MCP_PORT=8000 uv run python -m redflag_mcp

# Start from a packaged corpus instead of LanceDB
REDFLAG_CORPUS_PACKAGE=dist/corpus/redflag-corpus-2026.04.29.zip uv run python -m redflag_mcp
```

The server exposes hosted-client-compatible tools for request routing, semantic search, exact metadata filtering, source browsing, and filter discovery:

- `classify_red_flag_request` for deciding whether a request needs more context, exact metadata filtering, filtered semantic search, or direct semantic search
- `search_red_flags` for natural-language relevance search with sourced, ranked results
- `filter_red_flags` for exact metadata requests that should not use embedding search. Filters include `product_types`, `industry_types`, `customer_profiles`, `geographic_footprints`, `typology_family`, `transaction_patterns`, `category`, `risk_level`, `regulator`, `regulator_jurisdiction`, `issued_after`, `issued_before`, `regulatory_source`, `source_url`, and `source_id`.
- `get_red_flag` for the full text and citation metadata for one red flag
- `list_filters` for available metadata filter values
- `list_sources` and `get_source` for ingested source coverage and citation context

It is fully offline after ingestion or corpus installation — no API keys required at query time.

### Use from Codex

For local Codex threads, prefer stdio so Codex starts the MCP server automatically:

```bash
codex mcp add redflag-mcp -- zsh -lc 'cd /Users/learningmachine/Documents/Python-dev/redflag-mcp && HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 uv run python -m redflag_mcp'
```

Verify the registration:

```bash
codex mcp list
codex mcp get redflag-mcp
```

Then start a new Codex thread and ask for the server by name, for example:

```text
Use the redflag-mcp MCP server. List the available AML red flag filters.
```

If you already have the HTTP server running, you can register that instead:

```bash
codex mcp add redflag-mcp-http --url http://127.0.0.1:8000/mcp
```

### Local smoke checks

After ingesting the three target files, verify the tools with:

```text
list_filters
list_sources
classify_red_flag_request(query="what red flags apply to my crypto product?")
filter_red_flags(product_types=["depository"], category="fraud_nexus", risk_level="medium")
filter_red_flags(typology_family=["trade_based_money_laundering"], transaction_patterns=["trade_document_manipulation"])
filter_red_flags(regulator="FinCEN", issued_after="2024", issued_before="2026")
filter_red_flags(regulator_jurisdiction="FR")
search_red_flags(query="federal child nutrition program sponsor receives reimbursements inconsistent with its profile", product_types=["depository"])
search_red_flags(query="TBML invoice mismatch")
search_red_flags(query="southwest border oil company wires for waste oil or hazardous materials")
search_red_flags(query="bulk cash moved by armored car service to Mexico")
get_red_flag(red_flag_id="001_federal_child_nutrition_fraud-01")
```

For a vague query such as "what should I look for in business accounts?", the calling agent should call `classify_red_flag_request` and ask a brief consultation question covering product/channel, industry, customer profile, geography, and transaction channel or volume when the route is `needs_more_context`. For exact metadata requests such as "show medium-risk fraud nexus red flags for depository products" or "red flags from regulators in France", it should call `filter_red_flags` instead of semantic search, translating country names to `regulator_jurisdiction` codes such as `FR`, `SG`, `AU`, `GB`, `US`, and `EU`. For requests with both usable filters and a rich narrative, it should call `search_red_flags` with filters so metadata controls eligibility and embeddings rank the matching records.

---

## Development

```bash
uv sync --extra dev              # Install dependencies
uv run pytest tests/             # Run tests
uv run ruff check src/           # Lint
uv run mypy src/                 # Type check
```
