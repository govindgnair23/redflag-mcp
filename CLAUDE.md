# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
uv sync                                        # Install dependencies
uv run python -m redflag_mcp                   # Start MCP server (stdio mode)
uv run mcp dev src/redflag_mcp/server.py       # Run in MCP inspector
uv run python scripts/ingest.py                # Populate vector DB from YAML sources
uv run pytest tests/                           # Run full test suite
uv run pytest tests/test_tools.py             # Run a single test file
uv run ruff check src/                         # Lint
uv run mypy src/                               # Type check
```

## Architecture

This is an **MCP server** exposing AML (Anti-Money Laundering) red flag knowledge as queryable tools. Compliance officers ask natural-language questions; the server returns relevant, sourced red flags from a local vector database.

**Two distinct workflows:**

1. **Ingestion** (`scripts/ingest.py`): Reads YAML files from `data/source/`, auto-tags metadata via OpenAI API (`gpt-4o-mini`), embeds descriptions with `nomic-embed-text-v1.5`, upserts into LanceDB at `data/vectors/`.

2. **Query** (`src/redflag_mcp/server.py` + `tools.py`): FastMCP server loads the embedding model and opens the LanceDB store at startup (lifespan), then serves three read-only tools: `search_red_flags`, `get_red_flag`, `list_filters`.

**Module responsibilities:**

| Module | Role |
|---|---|
| `config.py` | Path constants, enums, embedding dimension (768) |
| `models.py` | Pydantic: `RedFlagSource` (YAML input), `RedFlagRecord` (LanceDB storage with vector), `RedFlagResult` (MCP response, no vector) |
| `embeddings.py` | Load `nomic-embed-text-v1.5`, `encode_documents()` (adds `"search_document: "` prefix), `encode_query()` (adds `"search_query: "` prefix) |
| `vectorstore.py` | LanceDB interface: `open_store`, `get_or_create_table`, `upsert_records`, `search`, `list_distinct_values` |
| `server.py` | FastMCP server with lifespan; selects stdio vs HTTP transport via `MCP_TRANSPORT` env var |
| `tools.py` | The three MCP tools, registered against the server |

## Critical Constraints

**stdout in stdio mode**: In stdio transport, stdout is the JSON-RPC channel. Any `print()` call anywhere in the codebase will corrupt the protocol. Use `logging` exclusively—never `print()`.

**Model download timing**: The `nomic-embed-text-v1.5` model (~275 MB) downloads on first call to `encode_documents()`. This should happen during ingestion, not on first MCP server startup (which would cause Claude Desktop connection timeouts). Running `scripts/ingest.py` before connecting Claude Desktop ensures the model is cached.

**LanceDB array filtering**: The `tags` and `product_types` fields are `list[str]`. LanceDB SQL-style `.where()` filtering on list columns may need validation—fall back to Python post-filtering if needed.

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
MCP client (Claude Desktop or HTTP agent)
```

## Transport

- **stdio** (default): for Claude Desktop / Claude Code
- **HTTP**: set `MCP_TRANSPORT=http`, `MCP_HOST`, `MCP_PORT` for OpenAI agents or other HTTP clients
