# redflag-mcp

MCP server exposing AML red flag knowledge as queryable tools. Compliance officers ask natural-language questions; the server returns relevant, sourced red flags from a local vector database.

## Overview

Three distinct workflows:

1. **Extraction** — pull AML red flags out of PDFs or web pages using an LLM and save them as YAML
2. **Ingestion** — embed the YAML files and load them into the local vector database
3. **Query** — MCP server answers semantic search queries against that database

---

## Extraction Pipeline

`scripts/extract.py` takes a regulatory document (PDF file or URL), sends its text to an OpenAI model, and writes a structured YAML file into `data/source/`. Each extracted entry includes a `source_url` linking back to the original document.

### Prerequisites

```bash
uv sync
export OPENAI_API_KEY=sk-...
```

### Adding PDFs in bulk (recommended workflow)

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
```

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
| `regulatory_source` | string | no | Source document name or authority (e.g. `FinCEN Alert FIN-2022-Alert001`) |
| `risk_level` | string | no | `high`, `medium`, or `low` |
| `category` | string | no | AML typology (e.g. `structuring`, `sanctions_evasion`, `shell_company`) |
| `simulation_type` | string | no | Optional simulation complexity code (e.g. `1A`, `2B`) |

### Deduplication

`data/source/.extracted_sources.yaml` tracks every processed source by its canonical path or URL. Sources already in the manifest are skipped in both batch and single-source mode. Use `--force` to re-extract a source regardless.

---

## Ingestion

After extraction, embed the YAML files and load them into the vector database:

```bash
uv run python scripts/ingest.py
```

This reads all YAML files in `data/source/`, generates embeddings with `nomic-embed-text-v1.5`, and upserts records into LanceDB at `data/vectors/`. Run this before connecting the MCP server to Claude Desktop — the ~275 MB embedding model downloads on first use and connection timeouts will occur if it happens at server startup.

---

## MCP Server

```bash
# Start server (stdio mode, for Claude Desktop / Claude Code)
uv run python -m redflag_mcp

# Start in MCP inspector
uv run mcp dev src/redflag_mcp/server.py

# Start as HTTP server (for OpenAI agents or other HTTP clients)
MCP_TRANSPORT=http MCP_HOST=0.0.0.0 MCP_PORT=8000 uv run python -m redflag_mcp
```

The server exposes three tools: `search_red_flags`, `get_red_flag`, and `list_filters`. It is fully offline after ingestion — no API keys required at query time.

---

## Development

```bash
uv sync                          # Install dependencies
uv run pytest tests/             # Run tests
uv run ruff check src/           # Lint
uv run mypy src/                 # Type check
```
