---
date: 2026-04-29
topic: downloadable-local-redflag-corpus
---

# Downloadable Local Red Flag Corpus

## Problem Frame

Financial institutions may want AML red flag retrieval without sending user queries, corpus data, or institution context to an external embedding API or hosted vector database. The current remote-MCP direction optimizes for easy hosted-client access, but it introduces runtime dependencies on external services. This brainstorm explores a simpler Lenny-style architecture: users or institutions download a complete red flag corpus package and run a read-only MCP server against that local package.

The goal is to preserve the core analyst value of red flag discovery, citations, source coverage, and guided narrowing while making the query path suitable for local desktop use and institution-hosted internal deployment.

## Requirements

**Distribution and Runtime Privacy**
- R1. The corpus must be distributable as a complete, versioned package that can be downloaded and used without live access to the source repository, external vector database, or embedding API.
- R2. The MCP query runtime must not require external API calls for search, ranking, filtering, citation lookup, or source browsing.
- R3. The same corpus package should support both local desktop MCP use and institution-hosted internal MCP deployment.
- R4. Each tool response should expose the corpus version or enough package metadata for users and auditors to know which corpus produced the answer.
- R5. The corpus package should include integrity metadata so users and institutions can verify that an installed package matches the released artifact.

**Search Without Runtime Embeddings**
- R6. Runtime search should use lexical retrieval rather than query embeddings, because local users cannot be expected to install or run an embedding model.
- R7. Search quality should be strengthened through rich metadata filters and curated synonym/query-expansion support, not through runtime semantic embeddings.
- R8. The search experience should support both broad keyword queries and exact metadata filtering for product type, industry, customer profile, geography, typology/category, risk level, source, and other curated facets.
- R9. The system should return deterministic, source-cited results with enough fit signals for an analyst to judge why a red flag matched.

**Corpus and Metadata Quality**
- R10. The corpus build process should enrich red flags with metadata broad enough to compensate for the loss of embedding-based semantic recall.
- R11. The metadata model should include curated aliases and synonyms for important AML terms, abbreviations, typologies, products, geographies, and transaction patterns.
- R12. Source coverage must remain inspectable: users should be able to list represented sources, inspect source-level summaries, and trace each red flag back to its source.
- R13. Corpus updates must be released as immutable versions with a clear update path and rollback path.
- R14. The corpus build should be reproducible from approved source records so institutions can inspect, rebuild, or validate a package instead of treating it as an opaque download.

**MCP Product Surface**
- R15. The MCP server should remain read-only and expose a small tool surface focused on search, exact filtering, red flag lookup, source browsing, and filter discovery.
- R16. The local and institution-hosted modes should provide the same analyst-facing tool behavior so documentation and evaluation can apply to both.
- R17. The server should be safe for stdio MCP use by avoiding stdout output outside the MCP protocol.
- R18. Institution-hosted deployments should be able to sit behind the institution's existing network and access controls, and query logging should be absent by default or explicitly configurable because analyst prompts may contain sensitive institution context.

## Success Criteria

- A local desktop user can download a corpus package, run the MCP server, and search red flags without an OpenAI key, vector database account, or local embedding model.
- An institution can host the same package internally so analyst queries and context stay within its environment.
- A user or institution can verify which corpus package is installed and whether it matches the released artifact.
- A query using an alias or abbreviation, such as "TBML" or "CVC", can still retrieve relevant records through curated synonym expansion and metadata.
- Exact requests such as "high-risk depository structuring red flags" return deterministic filtered results rather than approximate semantic matches.
- Every returned red flag includes source metadata and can be traced to the corpus version that produced it.
- Updating the corpus does not mutate a live dataset in place; users can identify, install, and roll back corpus versions.

## Scope Boundaries

- Do not require runtime embeddings, query-time OpenAI calls, Qdrant Cloud, or another hosted vector database for the local/offline query path.
- Do not make Google Drive, Dropbox, or any mutable shared folder the live runtime source of truth for serious deployments.
- Do not replace the remote-hosted MCP plan entirely; this is an alternative deployment model optimized for privacy and institutional control.
- Do not add write actions, corpus editing tools, alert decisioning, SAR conclusions, or automated compliance determinations to the MCP server.
- Do not require a rich UI; MCP tools remain the baseline interface.

## Key Decisions

- **Shared package foundation**: Support both local desktop and institution-hosted internal server modes from the same corpus package. This keeps the deployment choice separate from the corpus lifecycle.
- **Lexical search over runtime embeddings**: Local users should not need a large embedding model, GPU, or external embedding API. Search should be keyword-based at runtime.
- **Metadata and synonyms as the recall strategy**: AML terminology has many aliases, abbreviations, and adjacent phrases. Curated metadata and query expansion are the practical substitute for embedding recall.
- **Versioned artifacts over startup downloads from mutable storage**: A corpus package can be downloaded, verified, deployed, and rolled back. A live server fetching mutable data from Drive-style storage is harder to govern.
- **Read-only retrieval posture**: The system is easier to approve inside financial institutions when it is clearly an advisory retrieval tool with citations, not an automated decisioning system.

## Alternatives Considered

- **Current remote-MCP plan**: Cloud Run, OAuth, Qdrant Cloud, and OpenAI query embeddings provide easier hosted access and stronger semantic retrieval, but add external runtime dependencies and query-data exposure concerns.
- **Lenny-style direct startup download**: Simple and useful for public low-risk content, but too loose as the primary mechanism for governed AML corpus updates.
- **Packaged embeddings with runtime query embedding**: Reduces document embedding work at runtime, but still requires either an external embedding API or a local embedding model to embed user queries.
- **Pure keyword search without metadata/synonyms**: Lowest complexity, but likely too brittle for AML terminology and analyst workflows.

## Dependencies / Assumptions

- The red flag corpus is small enough for a complete local package to be practical on ordinary analyst or internal server machines.
- Source documents or extracted source text can be redistributed or referenced in a way compatible with their licensing and institution policy.
- Corpus enrichment can happen before package release, even if it uses external services during a controlled build process.
- Some financial institutions may accept external services during controlled corpus build/release more readily than during analyst query handling; others may require a fully internal rebuild path.

## Outstanding Questions

### Deferred to Planning
- [Affects R1, R5, R13][Technical] What package format best balances portability, integrity checking, and easy installation across local desktop and internal server deployment?
- [Affects R6, R8][Technical] Which lexical retrieval engine should be used for the first implementation?
- [Affects R7, R11][Product/Technical] What synonym and alias governance process is needed so query expansion improves recall without creating misleading matches?
- [Affects R10, R11][Technical] Which metadata fields beyond the current source model are needed for transaction patterns, aliases, source document title, jurisdiction, and typology families?
- [Affects R12][Needs research] Which source documents can be redistributed inside the corpus package versus referenced by URL only?
- [Affects R3, R16, R18][Technical] How should local desktop setup and institution-hosted setup differ while preserving the same MCP tool behavior?

## Next Steps

-> /ce:plan for structured implementation planning
