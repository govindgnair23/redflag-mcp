---
date: 2026-06-04
topic: mcp-filter-discoverability-attribution
---

# MCP Filter Discoverability and Attribution

## Problem Frame

Agents can search the AML red flag corpus successfully with natural language, but exact filtering still requires hidden knowledge about filter vocabularies, taxonomy semantics, and source attribution conventions. The failure mode is silent and expensive: a model may guess a token such as a country name, receive zero results, and conclude that the corpus has no relevant red flags even though the correct canonical token exists.

The product goal is to make the filter-first path as dependable as ranked search. A client inspecting the MCP tool manifest and calling available discovery tools should be able to find valid filter values, choose the right taxonomy dimension, enumerate cheaply, and attribute source material accurately without learning the corpus through accidental search results.

## Requirements

**Filter Vocabulary Discovery**
- R1. `geographic_footprints` must be discoverable through the same public mechanisms as other controlled filter facets, including `list_filters` and tool schema or description guidance.
- R2. `geographic_footprints` should expose canonical tokens such as `north_korea`, `sanctioned_jurisdiction`, `east_asia`, and `uk_eu` so agents do not have to infer them from search result metadata.
- R3. Tool guidance must distinguish regulator jurisdiction from geographic footprint: `regulator_jurisdiction` describes the issuing regulator's jurisdiction, while `geographic_footprints` describes the red flag's affected geography or typology geography.
- R4. Unknown exact filter values should produce a clear validation message where practical, especially for controlled-vocabulary facets, rather than silently returning zero results that look like a true negative.

**Tool Manifest Consistency**
- R5. Every tool description must reference only tools that are actually registered in the active MCP manifest.
- R6. If guidance tells agents to call `list_filters`, the manifest must include `list_filters`; if a deployment cannot expose it, guidance must be changed for that deployment.
- R7. `list_filters` must cover every exact-filter facet that agents are expected to choose from, including geography, subject, category, typology family, product type, industry type/group, customer profile, transaction pattern, risk level, regulator, and regulator jurisdiction.

**Taxonomy Semantics**
- R8. Tool descriptions and docs must explain the relationship between `category`, `subjects`, and `typology_family` directly in the retrieval surface, not only in external docs.
- R9. `category` should be documented as the primary classification of a record.
- R10. `subjects` should be documented as an eligibility/tagging layer for broad investigative topics that can catch cross-category records.
- R11. `typology_family` should be documented as a broader proceeds or typology grouping that may diverge from primary category.
- R12. The public guidance should include a concrete example: a darknet/crypto human-trafficking-relevant flag can have `category="virtual_currency"` while still matching `subjects=["human_trafficking"]`; therefore `category="human_trafficking"` alone is narrower than a subject filter.

**Enumeration and Result Shape**
- R13. Exact enumeration should support a concise result mode or field projection that returns only the fields needed for cheap paging, such as `id`, `description`, `regulatory_source`, `source_url`, and `risk_level`.
- R14. Metadata-only filter results should not include semantic-only fields such as empty `fit_signals` or absent `fit_explanation` unless those fields carry meaningful information for that path.
- R15. Agents should be able to enumerate a large filtered set cheaply and then call `get_red_flag` for full detail on selected records.
- R16. Tool descriptions must state that `filter_red_flags` uses cursor pagination for deterministic enumeration, while `search_red_flags` is ranked and should use a higher limit rather than a cursor.

**Attribution and Provenance**
- R17. The data model and retrieval responses must be able to represent interagency issuance with an `issuing_agencies`-style array or equivalent multi-agency attribution.
- R18. Single-value `regulator` may remain as a primary or legacy issuer facet, but responses must not force joint advisories into a misleading sole-agency attribution.
- R19. Source attribution should support cases such as DPRK cyber and IT worker advisories that are joint FinCEN/State/FBI or OFAC/FBI/CISA/State products.
- R20. Corpus integrity metadata must be either actionable or quiet: placeholder values such as `integrity_status: "unverified"` with zeroed hashes should not be returned as alarming noise unless documented with explicit agent guidance.

**Routing Guidance**
- R21. `classify_red_flag_request` should clearly state when the extra call is worth it: use it for ambiguous "what red flags apply" requests, skip it when the user already gives specific metadata filters or a concrete scenario.
- R22. Tool descriptions should preserve the distinction between exact metadata filtering and ranked relevance retrieval without using stale or misleading route names.

## Success Criteria

- An agent can answer "North Korea red flags" by discovering and applying the canonical geography token without relying on a lucky semantic search result.
- An agent inspecting the active manifest never receives instructions to call a missing tool.
- Broad topic requests such as human trafficking are routed to `subjects`, while strict primary-category requests still use `category`.
- Enumerating dozens of filtered records consumes substantially fewer tokens than returning full-detail records on every page.
- Joint advisories are attributed to all issuing agencies visible in the source material, not collapsed into a single regulator.
- Corpus integrity metadata no longer looks like a warning unless there is an actual integrity problem or a documented follow-up action.

## Scope Boundaries

- Do not replace ranked retrieval; natural-language search remains useful for relevance questions and scenario matching.
- Do not add a general boolean query language in this iteration. Discovery, subject filters, and concise enumeration address the observed filter-first failures.
- Do not require a full corpus rebuild solely to improve tool descriptions or filter discovery where active-store values can be derived at query time.
- Do not remove existing public fields such as `regulator`, `category`, or `typology_family`; clarify and extend them compatibly.
- Do not make ingestion reject source records only because a vocabulary expands, unless planning determines the facet is intentionally strict for query-time validation.

## Key Decisions

- **Expose geography as a first-class facet**: Geography caused the largest agent stumble, and it already behaves like a controlled vocabulary in practice.
- **Prefer `subjects` for investigative topics**: The server should own cross-field eligibility logic instead of making every client rediscover how `category`, `typology_family`, and transaction patterns relate.
- **Keep exact enumeration separate from ranked search**: Cursor pagination belongs to deterministic filtering; ranked search should stay limit-based and relevance ordered.
- **Represent joint issuance explicitly**: Accurate attribution is part of source trust, and a sole `regulator` field cannot model common interagency advisories.
- **Reduce noise in machine-facing responses**: Empty semantic fields and placeholder integrity metadata make agents spend context and reasoning on non-signals.

## Dependencies / Assumptions

- Existing retrieval-contract and subject-facet work may already satisfy part of this document; planning should audit current behavior before adding new implementation.
- The active hosted corpus and local vector mode may not expose identical metadata today; requirements apply to the public MCP contract, with compatibility decisions deferred to planning.
- Some agency attribution fixes may require source metadata enrichment in addition to query-tool response changes.

## Outstanding Questions

### Deferred to Planning

- [Affects R4][Technical] Which controlled facets should reject unknown values before store access versus returning zero matches for backward compatibility?
- [Affects R13][Technical] Should concise enumeration be exposed as a `mode`, `fields` projection, or a separate lightweight listing tool?
- [Affects R17][Technical] Should `issuing_agencies` be derived from source metadata, each red flag record, or both?
- [Affects R20][Technical] Is the current corpus integrity metadata placeholder generated during packaging, stored in SQLite metadata, or injected during response wrapping?
- [Affects R5, R6][Needs research] Which deployment path produced a manifest without `list_filters`, and does it reflect stale local code, hosted connector filtering, or registration drift?

## Next Steps

-> /ce:plan for structured implementation planning
