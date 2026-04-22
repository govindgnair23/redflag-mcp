# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Commands

```bash
uv sync --extra dev                            # Install dependencies
uv run python -m redflag_mcp                   # Start MCP server (stdio mode)
uv run mcp dev src/redflag_mcp/server.py       # Run in MCP inspector
uv run python scripts/ingest.py                # Populate vector DB from YAML sources
uv run python scripts/ingest.py data/source/001_federal_child_nutrition_fraud.yaml data/source/002_oil_smuggling_cartels.yaml data/source/003_bulk_cash_smuggling_repatriation.yaml  # Ingest only local target corpus
uv run pytest tests/                           # Run full test suite
uv run pytest tests/test_tools.py             # Run a single test file
uv run ruff check src/                         # Lint
uv run mypy src/                               # Type check
```

## Architecture

This is an **MCP server** exposing AML (Anti-Money Laundering) red flag knowledge as queryable tools. Compliance officers ask natural-language questions; the server returns relevant, sourced red flags from a local vector database.

**Two distinct workflows:**

1. **Ingestion** (`scripts/ingest.py`): Reads selected YAML files or all visible YAML files from `data/source/`, auto-tags missing metadata via OpenAI API (`gpt-4o-mini`) when `OPENAI_API_KEY` is available, embeds descriptions with `nomic-embed-text-v1.5`, and upserts into LanceDB at `data/vectors/`. Source YAML is not rewritten.

2. **Query** (`src/redflag_mcp/server.py` + `tools.py`): FastMCP server loads the embedding model and opens the LanceDB store at startup (lifespan), then serves three read-only tools: `search_red_flags`, `get_red_flag`, `list_filters`.

**Module responsibilities:**

| Module | Role |
|---|---|
| `config.py` | Path constants, strict enums, suggested consultation taxonomies, embedding dimension (768) |
| `models.py` | Pydantic: `RedFlagSource` (YAML input), `RedFlagRecord` (LanceDB storage with vector), `RedFlagResult` (MCP response, no vector) |
| `embeddings.py` | Load `nomic-embed-text-v1.5`, `encode_documents()` (adds `"search_document: "` prefix), `encode_query()` (adds `"search_query: "` prefix) |
| `vectorstore.py` | LanceDB interface: `open_store`, `get_or_create_table`, `upsert_records`, `search`, `get_by_id`, `list_distinct_values` |
| `server.py` | FastMCP server with lifespan; selects stdio vs HTTP transport via `MCP_TRANSPORT` env var |
| `tools.py` | The three MCP tools, registered against the server |

## Critical Constraints

**stdout in stdio mode**: In stdio transport, stdout is the JSON-RPC channel. Any `print()` call anywhere in the codebase will corrupt the protocol. Use `logging` exclusively—never `print()`.

**Model download timing**: The `nomic-embed-text-v1.5` model (~275 MB) downloads on first call to `encode_documents()`. This should happen during ingestion, not on first MCP server startup (which would cause Codex Desktop connection timeouts). Running `scripts/ingest.py` before connecting Codex Desktop ensures the model is cached.

**LanceDB array filtering**: `product_types`, `industry_types`, `customer_profiles`, and `geographic_footprints` are `list[str]`. The vector store uses Python post-filtering for list fields and scalar filters where reliable.

**OpenAI key for ingestion only**: `OPENAI_API_KEY` is needed only by `scripts/ingest.py` for auto-tagging. The MCP server itself is fully offline after ingestion.

## Data Flow

```
data/source/*.yaml
       ↓  scripts/ingest.py
       ↓  [OpenAI auto-tag missing metadata]
       ↓  [nomic embed descriptions]
data/vectors/  (LanceDB, gitignored)
       ↑  server.py lifespan
       ↑  tools.py search/get/list
MCP client (Codex Desktop or HTTP agent)
```

## Transport

- **stdio** (default): for Codex Desktop / Codex
- **HTTP**: set `MCP_TRANSPORT=http`, `MCP_HOST`, `MCP_PORT` for OpenAI agents or other HTTP clients
