# redflag-mcp

MCP server exposing AML red flag knowledge as queryable tools. Compliance officers ask natural-language questions; the server returns relevant, sourced red flags from a local vector database.

## Overview

Two distinct workflows:

1. **Extraction** — pull AML red flags out of a PDF or web page using an LLM and save them as YAML
2. **Ingestion** — embed the YAML files and load them into the local vector database
3. **Query** — MCP server answers semantic search queries against that database

---

## Extraction Pipeline

`scripts/extract.py` takes a regulatory document (PDF file or URL), sends its text to an OpenAI model, and writes a structured YAML file into `data/source/`.

### Prerequisites

```bash
uv sync
export OPENAI_API_KEY=sk-...
```

### Usage

```bash
# Extract from a URL
uv run python scripts/extract.py https://example.com/regulatory-guidance

# Extract from a local PDF
uv run python scripts/extract.py path/to/document.pdf

# Re-extract a source that was already processed
uv run python scripts/extract.py --force path/to/document.pdf
```

### What it does

1. **Fetches the document** — downloads the web page (strips nav/footer/scripts) or reads text from the PDF via pdfplumber
2. **Sends to OpenAI** — prompts `gpt-5.4-nano` (override with `OPENAI_EXTRACTION_MODEL`) to extract every distinct AML red flag indicator as structured JSON
3. **Validates** — each returned flag is checked against the `RedFlagSource` schema; invalid entries are skipped with a warning
4. **Writes YAML** — saves to `data/source/<slug>.yaml`, one entry per red flag
5. **Updates the manifest** — records the source in `data/source/.extracted_sources.yaml` to prevent accidental re-processing

### Output schema

Each entry in the YAML file has the following fields:

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | string | yes | Unique identifier, e.g. `fincen-alert-001-01` |
| `description` | string | yes | Standalone description of the red flag indicator |
| `product_types` | list[string] | no | Financial products this applies to (e.g. `depository`, `crypto`, `msb`) |
| `regulatory_source` | string | no | Source document or authority (e.g. `FinCEN Alert FIN-2022-Alert001`) |
| `risk_level` | string | no | `high`, `medium`, or `low` |
| `category` | string | no | AML typology (e.g. `structuring`, `sanctions_evasion`, `shell_company`) |
| `simulation_type` | string | no | Optional simulation complexity code (e.g. `1A`, `2B`) |

### Manifest

`data/source/.extracted_sources.yaml` tracks which sources have been processed. If you pass a source that is already in the manifest, the script exits early. Use `--force` to overwrite.

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
