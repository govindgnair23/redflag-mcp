---
date: 2026-04-29
topic: hosted-url-redflag-mcp-packaged-corpus
---

# Hosted URL Red Flag MCP With Packaged Corpus

## Problem Frame

Financial institutions may want AML red flag retrieval without sending user queries, corpus data, or institution context to an external embedding API or hosted vector database. The current remote-MCP direction optimizes for easy hosted-client access, but it introduces runtime dependencies on external services. This brainstorm explores a simpler Lenny-style architecture: users or institutions download a complete red flag corpus package and run a read-only MCP server against that local package.

The goal is to preserve the core analyst value of red flag discovery, citations, source coverage, and guided narrowing while making the query path suitable for local desktop use and institution-hosted internal deployment.

Follow-up refinement, 2026-05-06: the preferred first-run experience should also support the same simple connector posture as `lenny-mcp`: a user adds one public MCP URL in Claude, ChatGPT, or another hosted MCP client and enables the connector. In that mode, the corpus package remains the operator-facing deployment artifact, but normal users should not download files, install Python, run ingestion, or configure environment variables. The hosted service owns package activation, verification, and HTTP transport.

Primary product decision, 2026-05-06: the first shippable milestone is the hosted URL connector backed by a verified packaged corpus. Local desktop and institution-hosted deployments remain important follow-on paths, but the immediate end-user experience should be "add URL, enable connector, ask questions." The corpus package is the shared data artifact and deployment primitive, not the first thing public users handle.

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

**Hosted URL Connector**
- R19. The simplest public setup should be a hosted Streamable HTTP MCP endpoint where users add a single URL, such as `https://<deployment>/mcp`, and enable the connector.
- R20. The hosted endpoint must not require user-side package installation, local files, local Python, API keys, or manual corpus configuration.
- R21. Hosted deployment should run from a verified, pinned corpus artifact built by maintainers or CI, not from mutable source folders or startup extraction.
- R22. The hosted server should expose an operational health endpoint suitable for managed platforms, separate from the MCP endpoint if the framework does not already provide one. The health response should distinguish process liveness from corpus readiness.
- R23. Hosted deployment documentation should mirror the `lenny-mcp` simplicity: short connector setup instructions first, maintainer/deployment details second.
- R24. The Python implementation is acceptable; TypeScript is not required. The requirement is transport and deployment simplicity, not language parity.

**Original Source Files**
- R25. Original PDFs and source text should remain maintainer/build inputs, not runtime dependencies for the hosted connector.
- R26. Public source references should be preserved through source URLs, citation metadata, and the corpus manifest even when original files are not bundled.
- R27. Original documents or full extracted source text should only be included in a release artifact when source-level metadata explicitly clears redistribution; otherwise, use URL-only citation packaging.
- R28. URL-only source packaging should still preserve durable citation metadata: source title when known, regulator or publisher, publication date when known, retrieval date, source URL, and content hash where lawful and available.

**Privacy and Security Modes**
- R29. Public hosted mode must be documented as a convenience mode where user prompts are sent to the hosted MCP service operator and to the host client; it does not provide the same confidentiality boundary as local or institution-hosted mode.
- R30. Local desktop and institution-hosted modes should be documented as the privacy-preserving modes for institution-specific facts, customer details, transaction descriptions, or investigation context.
- R31. The public hosted endpoint must have an explicit access posture before launch: anonymous public, invite-only, OAuth-protected, or client-scoped. If it is anonymous, rate limits and request size limits are required.
- R32. Hosted deployment must avoid request-body logging by default, redact MCP payloads from application logs and traces, document platform access-log behavior, and set retention expectations.
- R33. Public HTTP inputs should have bounded limits for query length, filter cardinality, result limits, request body size, concurrency, and timeout behavior.

**Release and Runtime Defaults**
- R34. The hosted runtime should default to corpus mode and fail closed with a clear readiness error when no verified corpus is available; vector mode should be explicit development behavior.
- R35. Release builds should record deterministic provenance: source IDs, source record hashes, alias file hash, build tool version, dependency lock identity, build timestamp, enrichment provenance or human approval status, and corpus schema version.
- R36. Corpus release verification should have a trust model beyond hashes inside the ZIP: signed or externally published checksums, publisher identity, and documented behavior for verification failure.
- R37. Rollback should be defined as activating a previously verified corpus version by pinning a version or package path, then restarting or redeploying the server.

**Retrieval Acceptance**
- R38. Lexical retrieval quality should be validated against a small benchmark before public launch, covering aliases, paraphrases, typologies, product types, geography, and source-specific wording.
- R39. The first synonym scope should be bounded to aliases and abbreviations present in the initial corpus and representative test queries; broad synonym governance is deferred until evaluation identifies gaps.

## Success Criteria

- A local desktop user can download a corpus package, run the MCP server, and search red flags without an OpenAI key, vector database account, or local embedding model.
- An institution can host the same package internally so analyst queries and context stay within its environment.
- A public hosted deployment can be configured by end users by adding one MCP URL and enabling the connector, with no repository clone or local package setup.
- A first-time hosted user can complete a representative first query after connector setup without reading deployment documentation.
- A representative benchmark of AML retrieval queries returns relevant, source-cited results with acceptable analyst-reviewed quality before public launch.
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
- Do not require TypeScript or a Node runtime merely to match `lenny-mcp`; the existing Python FastMCP server can satisfy the URL-connector model.
- Do not expose raw original documents through the public connector unless redistribution has been reviewed and approved.
- Do not imply that the public hosted connector is appropriate for confidential institution-specific investigation details.
- Do not attempt broad taxonomy or synonym governance before the first public hosted deployment proves baseline retrieval quality.

## Key Decisions

- **Shared package foundation**: Support both local desktop and institution-hosted internal server modes from the same corpus package. This keeps the deployment choice separate from the corpus lifecycle.
- **Lexical search over runtime embeddings**: Local users should not need a large embedding model, GPU, or external embedding API. Search should be keyword-based at runtime.
- **Metadata and synonyms as the recall strategy**: AML terminology has many aliases, abbreviations, and adjacent phrases. Curated metadata and query expansion are the practical substitute for embedding recall.
- **Versioned artifacts over startup downloads from mutable storage**: A corpus package can be downloaded, verified, deployed, and rolled back. A live server fetching mutable data from Drive-style storage is harder to govern.
- **Read-only retrieval posture**: The system is easier to approve inside financial institutions when it is clearly an advisory retrieval tool with citations, not an automated decisioning system.
- **Hosted URL as the simplest end-user path**: For public use, the product should look like `lenny-mcp`: users add a URL and start asking questions. Corpus packaging, verification, and deployment are maintainer/operator responsibilities.
- **Source files are build inputs, not the hosted runtime store**: Keep original PDFs and text in the repository or controlled build storage for extraction and audit work. The hosted server should serve from the verified corpus package and cite source URLs rather than reading source documents live.
- **Public hosted is the first shipping path**: Build the first public experience around one hosted MCP URL. Local desktop and institution-hosted operation should reuse the same package and tools later, but should not slow down the first URL-based deployment.
- **Privacy modes must be explicit**: Public hosted mode optimizes setup simplicity, not maximum confidentiality. Local and institution-hosted modes are the right answer for sensitive institution-specific context.
- **Bound the first synonym effort**: Start with aliases and abbreviations visible in the initial corpus and benchmark queries. Expand only when retrieval evaluation shows concrete gaps.

## Alternatives Considered

- **Current remote-MCP plan**: Cloud Run, OAuth, Qdrant Cloud, and OpenAI query embeddings provide easier hosted access and stronger semantic retrieval, but add external runtime dependencies and query-data exposure concerns.
- **Lenny-style direct startup download**: Simple and useful for public low-risk content, but too loose as the primary mechanism for governed AML corpus updates.
- **Lenny-style hosted URL with pinned package**: Best fit for simple public connector setup. It borrows the one-URL user experience but avoids using mutable startup downloads as the authoritative corpus source.
- **Packaged embeddings with runtime query embedding**: Reduces document embedding work at runtime, but still requires either an external embedding API or a local embedding model to embed user queries.
- **Pure keyword search without metadata/synonyms**: Lowest complexity, but likely too brittle for AML terminology and analyst workflows.

## Dependencies / Assumptions

- The red flag corpus is small enough for a complete local package to be practical on ordinary analyst or internal server machines.
- Source documents or extracted source text can be redistributed or referenced in a way compatible with their licensing and institution policy.
- Corpus enrichment can happen before package release, even if it uses external services during a controlled build process.
- Some financial institutions may accept external services during controlled corpus build/release more readily than during analyst query handling; others may require a fully internal rebuild path.
- The first public hosted deployment can use public-source AML red flag content and does not need to accept confidential customer, transaction, or investigation details from users.
- Reviewed enrichment output may be treated as versioned source data when exact regeneration from an external LLM is not guaranteed.

## Outstanding Questions

### Deferred to Planning
- [Affects R1, R5, R13][Technical] What package format best balances portability, integrity checking, and easy installation across local desktop and internal server deployment?
- [Affects R6, R8][Technical] Which lexical retrieval engine should be used for the first implementation?
- [Affects R7, R11][Product/Technical] What synonym and alias governance process is needed so query expansion improves recall without creating misleading matches?
- [Affects R10, R11][Technical] Which metadata fields beyond the current source model are needed for transaction patterns, aliases, source document title, jurisdiction, and typology families?
- [Affects R12][Needs research] Which source documents can be redistributed inside the corpus package versus referenced by URL only?
- [Affects R3, R16, R18][Technical] How should local desktop setup and institution-hosted setup differ while preserving the same MCP tool behavior?
- [Affects R19, R22][Technical] Which hosted platform should be the first supported deployment target, and what health endpoint does it require?
- [Affects R21, R25][Technical] Should the public hosted deployment bake the corpus ZIP into the deployment artifact, fetch it from a release artifact at startup, or mount it from platform storage?
- [Affects R31][Product/Security] Should the first public endpoint be anonymous with rate limits, invite-only, or protected by hosted-client authentication?
- [Affects R38][Product] What exact query set and quality threshold are sufficient for the first public launch?

## Next Steps

-> /ce:plan for structured implementation planning
