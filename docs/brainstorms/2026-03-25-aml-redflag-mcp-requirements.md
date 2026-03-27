---
date: 2026-03-25
topic: aml-redflag-mcp
---

# AML Red Flag MCP Server

## Problem Frame

Compliance and BSA officers at financial institutions need to understand which AML red flags apply to their specific products and business lines. Regulatory guidance is scattered across FinCEN advisories, FATF guidance, OCC bulletins, and other sources — making it hard to assemble a complete, product-relevant picture. A queryable repository of curated red flags, accessible through a conversational agent like Claude, lets practitioners ask natural-language questions like "what red flags should I monitor for my money transmitter remittance product?" and receive relevant, sourced answers.

## Requirements

- R1. The system maintains a persistent database of AML red flags, where each entry includes: description text, product type(s), regulatory source, risk level (high/medium/low), and category/typology (e.g., structuring, layering, terrorist financing, fraud nexus).
- R2. Red flags can be queried via semantic search: a user provides natural-language context (e.g., product type, institution type, use case) and receives a ranked list of relevant red flags.
- R3. The MCP server exposes read-only tools that Claude can call to search and retrieve red flags.
- R4. Query results include enough metadata (source, risk level, category, product types) for a compliance officer to evaluate relevance and cite the source in their AML program documentation.
- R5. The database is populated by ingesting structured data files (JSON, CSV, or YAML). An ingestion CLI handles reading, LLM-assisted tagging of missing metadata, embedding generation, and storage.
- R6. Tags (product type, regulatory source, risk level, category) are generated at ingestion time by an LLM for any entries missing them, reducing manual curation effort.
- R7. The data layer is designed to scale from a few hundred to 1000+ entries without requiring architectural changes.

## Success Criteria

- A BSA officer can describe their product to Claude and receive a focused, relevant list of AML red flags with regulatory citations — without knowing tag names or taxonomy in advance.
- The maintainer can add new red flags by dropping entries into a structured file and running the ingestion script; the database updates without manual embedding or tagging work.
- Query results are accurate enough that a compliance officer can use them as a starting point for their SAR monitoring program or risk assessment.

## Scope Boundaries

- The MCP server is read-only; adding or editing red flags happens through the ingestion CLI, not through the agent.
- The system does not generate SAR narratives, transaction monitoring rules, or risk ratings — it surfaces relevant red flags only.
- The system does not integrate with transaction monitoring systems or core banking platforms.
- The initial data set is maintained by the project owner; the system does not crawl regulatory sites or auto-update from external sources.

## Key Decisions

- **Semantic search over structured tag filtering**: Natural-language context from the user drives retrieval, so compliance officers don't need to know the exact taxonomy to find relevant flags. Optional metadata filters (product type, risk level, category) can further narrow results.
- **Read-only MCP interface**: Write operations happen through a separate ingestion CLI. This keeps the MCP surface simple and safe for agent use.
- **LLM-assisted tagging at ingestion time**: Tags are generated once when a record is ingested, not at query time. This keeps query latency low and makes the metadata stable and auditable.
- **Vector database for storage**: Given the target scale of 1000+ entries, a local vector store (e.g., ChromaDB or LanceDB) is the appropriate persistence layer — more capable than in-memory, simpler than a hosted service.

## Dependencies / Assumptions

- The project is Python-based and uses `uv` for dependency management.
- The MCP server will run as a local stdio process, compatible with Claude Desktop and Claude Code.
- An LLM API (Claude) is available for tag generation during ingestion.
- The project owner curates the source data files; the system does not need to validate data quality beyond basic schema checks.

## Outstanding Questions

### Deferred to Planning

- [Affects R2, R3][Technical] Which vector store to use: ChromaDB vs. LanceDB vs. SQLite + vector extension — evaluate based on persistence model, Python SDK maturity, and uv compatibility.
- [Affects R2][Technical] Which embedding model to use for indexing and query encoding: a local model (e.g., `sentence-transformers`) vs. the Voyage or OpenAI embeddings API.
- [Affects R3][Technical] What MCP tools to expose and their exact signatures — e.g., `search_red_flags(query, filters?, limit?)`, `list_product_types()`, `get_red_flag(id)`.
- [Affects R5, R6][Technical] What structured file format to use as the canonical source of truth for red flags (JSON array, YAML, or CSV), and whether to version it in git.

## Next Steps

→ `/ce:plan` for structured implementation planning
