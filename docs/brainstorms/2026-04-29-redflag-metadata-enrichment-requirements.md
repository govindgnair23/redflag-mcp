---
date: 2026-04-29
topic: redflag-metadata-enrichment-for-lexical-search
---

# Red Flag Metadata Enrichment for Lexical Search

## Problem Frame

The planned SQLite FTS5 corpus (see corpus plan Unit 1) enables offline keyword search, but
lexical recall is only as strong as the text and metadata indexed. The current YAML source model
captures product types, industry types, customer profiles, geographic footprints, category, risk
level, and a prose description. BSA analysts routinely search using AML acronyms (TBML, CVC, MSB),
typology family names (trade-based money laundering, sanctions evasion), and behavioral shorthand
(structuring, smurfing, round-tripping) that are absent from most descriptions and unrepresented
in any structured field. Without enrichment, these common analyst queries return zero results even
when clearly relevant records exist.

The corpus build process can enrich records with additional structured metadata before packaging.
This enrichment needs to be auditable, deterministic, and written back to the YAML source files so
the enriched record is the inspectable source of truth — not a transient build-time artifact.

## Requirements

### Curated Lexicon (aliases.yaml)

- R1. Create `data/lexicon/aliases.yaml` as a curated, source-controlled file that maps AML
  abbreviations, acronyms, and shorthand terms to their canonical expansion(s). The initial set
  must cover at minimum: TBML, CVC, MSB, CTR, SAR, BSA, NPO, PEP, SFPF, KYC, CDD, EDD, FATF,
  DNFBP, hawala, smurfing.
- R2. Each alias entry must map a normalized lookup term to one or more canonical expansion strings
  that appear in red flag descriptions or metadata values.
- R3. The corpus build process must embed the full aliases.yaml into each corpus package so query
  expansion is deterministic and identical across all installations of the same package version.
- R4. Query expansion at search time must use only the embedded alias lexicon — no runtime LLM
  inference and no external API calls.

### New Structured Fields on YAML Source Records

- R5. Add a `typology_family` field (list of strings) to `RedFlagSource` and all downstream
  models. This field groups the red flag under one or more named AML typology families.
  - Core controlled vocabulary (initial): `trade_based_money_laundering`,
    `crypto_asset_money_laundering`, `real_estate_money_laundering`, `sanctions_evasion`,
    `corruption_and_bribery`, `human_trafficking_proceeds`, `narcotics_proceeds`,
    `fraud_proceeds`, `tax_evasion`, `terrorist_financing`, `proliferation_financing`.
  - When no core vocabulary term fits, the LLM may assign a free-form label; free-form labels
    from the corpus build output should be reviewed and promoted to the core vocabulary over time.
- R6. Add a `transaction_patterns` field (list of strings) to `RedFlagSource` and all downstream
  models. This field labels discrete behavioral patterns present in the red flag.
  - Core controlled vocabulary (initial): `structuring`, `rapid_fund_movement`,
    `wire_transfer_chains`, `cash_intensive_behavior`, `trade_document_manipulation`,
    `shell_company_usage`, `real_estate_transactions`, `cryptocurrency_mixing`,
    `loan_back_scheme`, `round_tripping`, `informal_value_transfer`, `third_party_payments`.
  - Free-form overflow permitted for patterns not yet in the vocabulary, subject to the same
    review-and-promote process as typology_family.
- R7. Add a `key_terms` field (list of strings) to `RedFlagSource` and all downstream models.
  This field holds short extracted phrases that are specific, searchable, and not already captured
  by the prose description or other metadata fields. Target content includes: named instruments
  (CTR, cashier's check, wire transfer, prepaid card), regulatory thresholds ($10,000, $3,000),
  entity types (NPO, shell company, foreign financial institution), and regulatory references
  (FinCEN advisory, FFIEC guidance).
  - key_terms are free-form; no controlled vocabulary. They must be short, searchable phrases,
    not sentences.

### LLM Extraction at Build Time

- R8. Extend the build-time LLM tagger (`scripts/ingest.py` or a new corpus build script) to
  extract and populate `typology_family`, `transaction_patterns`, and `key_terms` for records
  where these fields are absent or empty.
- R9. The tagger prompt for new fields must:
  - Provide the full controlled vocabulary lists for `typology_family` and `transaction_patterns`
    with instructions to prefer core terms and use free-form only when none apply.
  - Instruct the model to extract `key_terms` as short searchable phrases, not paraphrases.
  - Return only the missing fields as a JSON object (consistent with the existing tagger pattern).
- R10. All three new fields must be written back to the YAML source file as the authoritative
  enriched record. The YAML source file becomes the single source of truth; the corpus build reads
  these fields directly on subsequent builds without re-calling the LLM.

### Backward Compatibility and Validation

- R11. All three new fields must be optional with empty-list defaults. Existing YAML source files
  without these fields must validate without modification.
- R12. `typology_family` and `transaction_patterns` must warn (not fail) during corpus build when
  a free-form value is used that does not appear in the controlled vocabulary. This surfaces
  candidates for vocabulary promotion without blocking the build.
- R13. `key_terms` entries must be validated to be non-empty strings; no other structural
  constraint applies.

### Searchable Text Synthesis

- R14. The corpus builder must synthesize a `search_text` column for FTS5 indexing that
  concatenates: description + category + typology_family values + transaction_patterns values +
  key_terms + alias expansions for any recognized terms in the record. This column is not stored
  in the YAML; it is derived at build time from the enriched record and the embedded lexicon.
- R15. All original structured fields (`product_types`, `industry_types`, `customer_profiles`,
  `geographic_footprints`, `risk_level`, `regulatory_source`) must remain queryable as metadata
  filters independent of the FTS index.

## Success Criteria

- A search for "TBML" or "trade based money laundering" retrieves the same import/export or
  trade-finance red flag records through alias expansion.
- A search for "smurfing" retrieves structuring red flags even if the word "smurfing" does not
  appear in any description.
- Red flag records can be filtered by `typology_family = "sanctions_evasion"` to return only
  sanction-related flags.
- A search for "CTR" or "cashier's check" retrieves records that reference those instruments.
- All three new fields are present in the YAML source files after the enrichment pass, and
  rebuilding the corpus from those files does not re-call the LLM for already-enriched records.
- Corpus packages built from the same enriched YAML files produce the same FTS index content.

## Scope Boundaries

- Do not add new controlled vocabulary values or alias entries at query time. Vocabulary and
  lexicon updates happen in source-controlled data files, not at runtime.
- Do not require the LLM for query-time search. Alias expansion uses only the embedded lexicon.
- Do not redesign the existing metadata fields (product_types, industry_types, etc.). The new
  fields add coverage; they do not replace or rename existing fields.
- Do not bundle full source documents inside the corpus package in this enrichment work. Source
  redistribution policy is handled separately in source_metadata.yaml per the corpus plan.
- Do not make `key_terms` a controlled vocabulary. It is meant to capture instrument names and
  phrases that cannot be enumerated in advance.

## Key Decisions

- **Curated-first aliases.yaml as the primary recall mechanism**: Acronym and jargon recall is
  the highest-priority gap. A curated lexicon with human-approved expansions is deterministic,
  auditable, and free of hallucination risk, making it the right primary mechanism.
- **Controlled vocabulary with free-form overflow for typology_family and transaction_patterns**:
  A pure controlled vocabulary would miss emerging patterns; pure free-form would produce
  inconsistent facets. Hybrid allows faceting on known types while capturing new patterns for
  vocabulary review.
- **Write-back to YAML source files**: Enrichment that lives only in build-time state must be
  regenerated (and re-reviewed) on every corpus rebuild. Writing back to YAML makes enriched
  records inspectable, diffable in git, and stable across rebuilds.
- **Synthesized search_text column for FTS**: Separate structured fields enable exact filtering;
  the synthesized column enables broad keyword search across all enriched dimensions in a single
  FTS query.

## Dependencies / Assumptions

- The corpus build process has access to an OpenAI API key (or equivalent) for the enrichment
  pass. Query-time operation remains fully offline.
- Enrichment pass output for records already containing all three fields is a no-op; the tagger
  should skip fully-enriched records to avoid unnecessary LLM calls.
- The initial controlled vocabulary sets for `typology_family` and `transaction_patterns` cover
  the three existing source files adequately; the corpus plan Unit 1 can validate this against
  `001_federal_child_nutrition_fraud.yaml`, `002_oil_smuggling_cartels.yaml`, and
  `003_bulk_cash_smuggling_repatriation.yaml`.

## Outstanding Questions

### Deferred to Planning

- [Affects R1, R4][Technical] What is the exact YAML schema for aliases.yaml entries (one-to-many
  expansion, normalization rules, case folding)?
- [Affects R5, R6][Technical] How should free-form overflow values be surfaced in the build
  output for human review — log warning, separate report file, or annotated field value?
- [Affects R14][Technical] What tokenizer and column weighting settings for FTS5 best match the
  synthesized search_text content for AML terminology?
- [Affects R8, R10][Technical] Should the write-back use in-place YAML mutation or a sorted
  canonical serialization to keep git diffs clean?
- [Affects R9][Needs research] What prompt structure produces the most consistent controlled
  vocabulary selection versus free-form overflow behavior from gpt-4o-mini?

## Next Steps

-> /ce:plan for structured implementation planning
