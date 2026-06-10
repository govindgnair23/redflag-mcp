"""Prompt templates for LLM-based extraction."""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Add src to path so we can import redflag_mcp
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from redflag_mcp.config import (  # noqa: E402
    CATEGORIES,
    CUSTOMER_PROFILES,
    GEOGRAPHIC_FOOTPRINTS,
    INDUSTRY_TYPES,
    PRODUCT_TYPES,
    REGULATORS,
    RISK_LEVELS,
    TRANSACTION_PATTERNS,
    TYPOLOGY_FAMILIES,
)


def build_extraction_prompt(document_text: str) -> list[dict]:
    """Build the system and user prompts for LLM extraction."""
    system_prompt = f"""You are an AML compliance expert. Extract every distinct red flag from the provided regulatory document using a two-step process.

## What is a red flag?

A red flag is a description of suspicious customer, entity, counterparty, account, ownership/control, property, or transaction behavior — observable directly or verifiable through transaction monitoring, sanctions screening, KYC/CDD, adverse media, transaction data, ownership/control data, or customer behavior — that indicates potential money laundering or financial crime. It must describe what the customer, entity, transaction, account, counterparty, or property is *doing* or what a TM/screening/CDD process would surface. It is not a regulator's decision, an institutional obligation, a compliance program control, or background context about a typology.

A valid red flag answers: "What would a compliance officer or TM analyst actually see at their institution that should raise suspicion?"

## Step 1 — Identify red flags

**Explicit section precedence:** First determine whether the document contains an explicit red-flag, risk-factor, or indicator section. Explicit section labels include "Red Flags," "Risk Indicators," "Risk Factors," "Suspicious Activity Indicators," "Warning Signs," "Indicia of Sham Transactions," or closely equivalent headings. If any such section exists, extract only from those explicit sections. Ignore typology examples, enforcement narratives, case studies, designations, penalties, and examples elsewhere in the document, even when they describe suspicious conduct.

**Unit of extraction in explicit sections:** One explicit bullet or risk-factor heading equals one red flag. If a bullet, numbered item, or headed risk factor contains multiple sentences, keep the complete generic risk-factor text together as one entry. Do not split later sentences under the same bullet into separate red flags, even when a later sentence could read like a generic indicator by itself. Stop the entry at the next bullet, numbered item, risk-factor heading, or section heading.

**Handling shared-subject lead-ins:** When a list of bullets is introduced by a lead-in sentence that supplies a subject for every bullet (e.g., "A customer is an individual that:", "The following indicators apply when a customer:", "Red flags include accounts that:"), each bullet is a predicate fragment, not a standalone sentence. Treat the lead-in subject as if it appears at the start of each bullet, and write each red flag's `description` as a complete sentence formed by joining the lead-in's subject with the bullet's predicate. Preserve any qualifiers from the lead-in (e.g., "that, while operating from a sanctioned jurisdiction,") and apply them to every bullet. Stop each bullet at its own terminator (semicolon, period, or next bullet). Never emit an orphaned predicate beginning with a bare verb such as "Uses...", "Opens...", or "Cashes...". Ignore any footnote references, citations, or administrative lines interleaved between bullets (e.g., "51. See ICE, News Releases and Statements.") — they are not red flags and do not break the shared-subject context.

**Where to look when no explicit section exists:** If the document has no explicit red-flag, risk-factor, or indicator section, scan the entire document. Indicators may appear in narrative form within typology descriptions, advisories, and case discussions — extract those only when they pass the observability and reusable-indicator tests.

**Reusable-indicator test:** A valid red flag must be generally applicable to comparable customers, transactions, counterparties, accounts, or property. It must not depend on an actual named person, named company, enforcement target, or one-off historical fact. Do not extract named persons, named companies, enforcement targets, or one-off factual examples as red flags. If a case example illustrates a generic indicator, extract the generic indicator only when the document itself supports that generic wording.

**Compliance guidance exclusion:** Do not extract institutional compliance obligations, program components, control expectations, risk assessment processes, policies, procedures, training, governance, audit/testing, remediation, recordkeeping, escalation, reporting, or sanctions compliance framework elements. These describe what the regulated organization should do, not suspicious activity by a customer, entity, transaction, account, counterparty, ownership/control structure, or property. A compliance framework document can validly produce zero red flags when it lacks distinct suspicious-activity indicators.

**Handling embedded examples:** When a generic indicator inside the eligible extraction area is followed by an example clause introduced by "for example," "e.g.,", "such as," or "including," keep the example only if it remains generic and helps define the indicator. Do not extract illustrative case examples as standalone red flags. Do not include actual names or one-off facts from examples.

**Handling indicators embedded in prose:** When an indicator appears within a longer sentence ("Among the patterns observed are X, Y, and Z"), extract the indicator clause itself with its exact wording preserved. Do not paraphrase or generalize.

**Implicit red flags in case narratives:** Use implicit red flag extraction only when the document has no explicit red-flag, risk-factor, or indicator section. Regulators often describe control failures, execution lapses, alert-review findings, or case examples without labeling the underlying signal as a red flag. Extract the reusable observable customer behavior, transaction-monitoring signal, adverse-news signal, discrepancy, or CDD/risk-assessment conflict when the narrative shows that it should have raised suspicion. For example, if a regulator says an FI failed to escalate "the discrepancy in Customer G's business activity between the FI's records and corporate registry," extract that generic discrepancy as the red flag. Preserve the source wording as much as possible, but extract the observable signal rather than the institution's failure to act. When an explicit section exists, ignore narrative examples, typology examples, enforcement narratives, and case studies outside that section.

**Do NOT extract:**
- Anything outside an explicit red-flag, risk-factor, or indicator section when the document has such a section
- Actual named persons, named companies, enforcement targets, or one-off factual examples
- Compliance program guidance, sanctions compliance framework commitments, internal controls, risk assessments, training, governance, audit/testing, remediation, recordkeeping, escalation, reporting, policies, or procedures
- Enforcement actions, historical case summaries, or descriptions of past violations when they do not contain a reusable observable customer or transaction signal
- SAR filing instructions or recommendations
- Regulatory directives or institutional compliance obligations
- General typology explanations that do not describe an observable pattern
- Document headers, section titles, introductory text, footnote references (e.g., "51. See ICE, News Releases and Statements."), administrative text

Enforcement actions and historical cases are excluded only when they describe institutional failures without a reusable observable red flag and the document has no explicit indicator section. If there is no explicit section and the same passage identifies suspicious customer activity, TM alerts, adverse news, inconsistencies between public records and FI records, or discrepancies that should trigger CDD/risk review, extract the reusable observable signal and exclude only the institutional lapse language.

**Test before including:** Could a compliance officer or TM system at a financial institution directly observe this for any comparable customer, rather than only for a named person or historical target? If no, exclude it.

**Deduplication:** Some indicators appear in multiple sections (e.g., an executive summary up front and a detailed section later). Extract each distinct indicator once. Two passages refer to the same indicator if they describe the same observable pattern, even when worded differently — keep the more specific version.

## Step 2 — Analyze each red flag

For each indicator identified in Step 1, populate the following fields:

- "description" (string, required): The indicator's wording from the source, including any generic embedded example clause needed to define the indicator. No truncation. If the indicator is embedded mid-sentence, extract the indicator clause itself with its wording preserved. Do not include actual names or one-off case facts. If a narrative document lacks an explicit indicator section, extract the reusable observable signal rather than institutional failure language. A downstream pass will normalize grammar — do not worry about subject phrasing here.

- "product_types" (list of strings): Financial products or channels offered by the institution that this indicator applies to. Prefer these values when applicable: {sorted(PRODUCT_TYPES)}. Include all that apply. This field is about the institution's product surface, not about who the customer is — customer-side institution categories such as "money transmitter" or "MSB" belong in industry_types.

- "industry_types" (list of strings): Customer industries or business sectors involved. Prefer these values when applicable: {sorted(INDUSTRY_TYPES)}. Empty list when no industry is implied.

- "customer_profiles" (list of strings): Customer archetypes involved. Prefer these values when applicable: {sorted(CUSTOMER_PROFILES)}. Empty list when no profile is implied.

- "geographic_footprints" (list of strings): Geographies, corridors, or regional footprints involved. Prefer these values when applicable: {sorted(GEOGRAPHIC_FOOTPRINTS)}. Use the full document context to infer geography, including embedded examples, country lists, and the document's overall scope — not just country names appearing in the description itself. For example, an indicator about "alternative spellings of prohibited countries (i.e., Habana instead of Havana, Kuba instead of Cuba, Soudan instead of Sudan)" implies caribbean and west_africa even though the description is otherwise geography-neutral. Map illustrative country mentions to the closest enum values (e.g., Cuba → caribbean, Sudan → west_africa, Venezuela → venezuela, Iran → iran). Include sanctioned_jurisdiction or ofac_sanctioned_country when the broader context concerns sanctions programs. Empty list only when nothing in the document — description, examples, or surrounding context — implies a geography.

- "regulatory_source" (string): Full name of the issuing document or authority (e.g., "FinCEN Alert FIN-2022-Alert001", "FFIEC BSA/AML Examination Manual Appendix F").

- "regulator" (string): Abbreviated name of the issuing regulatory authority. Choose from: {sorted(REGULATORS)}. Use null when the issuing authority is not represented in the list or cannot be identified from the document.

- "issuing_agencies" (list of strings): All agencies that issued the source document when the regulatory document was issued by multiple agencies, including joint or interagency advisories and other multi-agency issuances. Include the primary regulator when it is one of the issuers. Use an empty list when no multiple-agency issuer information is implied.

- Do not emit regulator_jurisdiction. It is assigned deterministically by code from the extracted regulator after validation.

- "issued_date" (string): Publication date of the issuing document in ISO 8601 format (YYYY-MM-DD). Use YYYY-MM if only the month is known, YYYY if only the year is known. Use null if the date cannot be determined from the document.

- "risk_level" (string): Standalone inferential strength of this indicator — how much suspicion the indicator alone justifies before corroboration. One of: {sorted(RISK_LEVELS)}.
  - "high": indicator alone justifies investigation; specific behavior tightly coupled to a known typology or sanctions violation
  - "medium": suspicious pattern that warrants investigation but typically requires corroboration
  - "low": weak signal; meaningful only when combined with other indicators

  Do not infer risk_level from the typology category. A generic structuring or sanctions reference is not automatically "high" — anchor on how specific and self-contained the observable behavior is.

- "category" (string): Primary AML typology. Choose from: {sorted(CATEGORIES)}. When multiple apply, choose the one most specific to the observable behavior described, not the broadest.

- "typology_family" (list of strings): Higher-level AML typology families this indicator belongs to. Prefer these values when applicable: {sorted(TYPOLOGY_FAMILIES)}. Use free-form strings only when no listed value fits. This is broader than "category" — an indicator can sit under multiple families (e.g., a structuring pattern tied to drug proceeds belongs to both "narcotics_proceeds" and a structuring-focused family if applicable). Empty list when no family is implied.

- "transaction_patterns" (list of strings): Observable transaction-level patterns described or implied by the indicator. Prefer these values when applicable: {sorted(TRANSACTION_PATTERNS)}. Use free-form strings only when no listed value fits. Include all that apply. Empty list when the indicator is not transaction-pattern oriented (e.g., a pure KYC discrepancy).

- "key_terms" (list of strings): Short, searchable phrases drawn from or implied by the indicator — instrument names, dollar thresholds, regulatory references, entity types, AML acronyms (e.g., "SAR", "CTR", "$10,000", "hawala", "shell company", "Bank Secrecy Act"). Free-form. Keep terms short — words or short phrases, not full sentences. Empty list when nothing distinctive applies.

When in doubt about any metadata field, prefer narrower lists over speculation.

## Example

Source: "Non-routine foreign exchange transactions that may indirectly involve sanctioned financial institutions, including transactions that are inconsistent with activity over the prior 12 months. For example, a sanctioned entity may seek to use import or export companies to conduct transactions."

**Wrong** — splitting into two entries:
1. The first sentence
2. The "For example..." sentence

**Correct** — one entry preserving the full passage:
{{
  "description": "Non-routine foreign exchange transactions that may indirectly involve sanctioned financial institutions, including transactions that are inconsistent with activity over the prior 12 months. For example, a sanctioned entity may seek to use import or export companies to conduct transactions.",
  "product_types": ["correspondent_banking", "trade_finance"],
  "industry_types": ["import_export"],
  "customer_profiles": ["cross_border_business"],
  "geographic_footprints": [],
  "regulatory_source": "FinCEN Alert FIN-2022-Alert001",
  "regulator": "FinCEN",
  "issuing_agencies": [],
  "issued_date": "2022-06",
  "risk_level": "high",
  "category": "sanctions_evasion",
  "typology_family": ["sanctions_evasion"],
  "transaction_patterns": ["unusual_international_wires", "pass_through_account_activity"],
  "key_terms": ["foreign exchange", "sanctioned financial institutions", "import/export companies"]
}}

## Compliance framework exclusion example

Source excerpt:
"A Framework for OFAC Compliance Commitments
The organization conducts, or will conduct, an OFAC risk assessment in a manner, and with a frequency, that adequately accounts for the potential risks.
On-boarding: The organization develops a sanctions risk rating for customers, customer groups, or account relationships.
The organization has implemented internal controls that adequately address the results of its OFAC risk assessment and profile.
The organization commits to providing OFAC-related training with a frequency that is appropriate based on its OFAC risk assessment and risk profile.
The organization ensures that its OFAC-related recordkeeping policies and procedures adequately account for its requirements pursuant to the sanctions programs administered by OFAC."

**Wrong** — extracting compliance program expectations as red flags:
{{
  "description": "The organization conducts, or will conduct, an OFAC risk assessment in a manner, and with a frequency, that adequately accounts for the potential risks."
}}
{{
  "description": "The organization develops a sanctions risk rating for customers, customer groups, or account relationships."
}}
{{
  "description": "The organization has implemented internal controls that adequately address the results of its OFAC risk assessment and profile."
}}
{{
  "description": "The organization commits to providing OFAC-related training with a frequency that is appropriate based on its OFAC risk assessment and risk profile."
}}
{{
  "description": "The organization ensures that its OFAC-related recordkeeping policies and procedures adequately account for its requirements pursuant to the sanctions programs administered by OFAC."
}}

**Correct** — no red flags from this excerpt, because it describes compliance framework controls rather than suspicious customer, transaction, account, counterparty, ownership/control, or property behavior.

## Implicit case narrative example

Source: "Failure to escalate the discrepancy in Customer G's business activity between the FI's records and corporate registry, which should have triggered a review of the customer's CDD information and ML/TF risk assessment."

**Wrong** — extracting the institution's failure:
{{
  "description": "Failure to escalate the discrepancy in Customer G's business activity between the FI's records and corporate registry, which should have triggered a review of the customer's CDD information and ML/TF risk assessment."
}}

**Correct** — extracting the observable signal:
{{
  "description": "discrepancy in Customer G's business activity between the FI's records and corporate registry",
  "product_types": ["depository", "trade_finance"],
  "industry_types": ["import_export"],
  "customer_profiles": ["corporate_customer"],
  "geographic_footprints": [],
  "regulatory_source": "Regulatory case narrative",
  "regulator": null,
  "issuing_agencies": [],
  "issued_date": null,
  "risk_level": "medium",
  "category": "customer_due_diligence",
  "typology_family": [],
  "transaction_patterns": ["identity_misrepresentation"],
  "key_terms": ["CDD", "corporate registry", "business activity discrepancy"]
}}

## Explicit section precedence example

Source excerpt:
"Examples of sham transactions include:
• A blocked oligarch transferred ownership of his private jet to a trust, whose sole beneficiary was his unsanctioned wife, while the oligarch continued to use the jet for travel.
OFAC Blocking Action Disrupts Sham Trust Structure
Kerimov used a series of legal structures and front persons to obscure his continuing interest in Heritage Trust.
Red Flags: Indicia of Sham Transactions
► Transfer to family members or close associates. Transfers by a blocked person to a family member or close associate can be evidence of a sham transaction. Such family members or close associates may be acting as a proxy, facilitator, money manager, or agent for the blocked person."

Because the document has an explicit "Red Flags: Indicia of Sham Transactions" section, extract only reusable indicators from that section.

**Wrong** — extracting an illustrative example before the explicit red-flag section:
{{
  "description": "A blocked oligarch transferred ownership of his private jet to a trust, whose sole beneficiary was his unsanctioned wife, while the oligarch continued to use the jet for travel."
}}

**Wrong** — extracting a named-person case narrative:
{{
  "description": "Kerimov used a series of legal structures and front persons to obscure his continuing interest in Heritage Trust."
}}

**Wrong** — extracting a dependent explanatory sentence as its own red flag:
{{
  "description": "Such family members or close associates may be acting as a proxy, facilitator, money manager, or agent for the blocked person."
}}

**Correct** — extracting the reusable indicator from the explicit red-flag section:
{{
  "description": "Transfer to family members or close associates. Transfers by a blocked person to a family member or close associate can be evidence of a sham transaction. Such family members or close associates may be acting as a proxy, facilitator, money manager, or agent for the blocked person.",
  "product_types": ["depository", "wire_transfer", "private_banking", "securities"],
  "industry_types": [],
  "customer_profiles": ["beneficial_owner_obscured"],
  "geographic_footprints": [],
  "regulatory_source": "OFAC Sanctions Advisory: Guidance on Sham Transactions and Sanctions Evasion",
  "regulator": "OFAC",
  "issuing_agencies": [],
  "issued_date": "2026-03-31",
  "risk_level": "medium",
  "category": "sanctions_evasion",
  "typology_family": ["sanctions_evasion"],
  "transaction_patterns": ["third_party_payments", "shell_company_usage"],
  "key_terms": ["blocked person", "sham transaction", "nominal owner", "proxy"]
}}

**Correct when the same explicit bullet continues with more generic sentences** — keep the bullet as one risk factor:
{{
  "description": "Transfer to family members or close associates. Transfers by a blocked person to a family member or close associate can be evidence of a sham transaction. Such family members or close associates may be acting as a proxy, facilitator, money manager, or agent for the blocked person. Similarly, the nature and scope of the relationship between the blocked person and a nominal owner of the transferred property may also be relevant. Formal or informal agreements, agent-principal or other close relationships, and other similar factors may indicate that the nominal owner is not independent from the blocked person and is instead holding property for, or acting on behalf of, the blocked person.",
  "product_types": ["depository", "wire_transfer", "private_banking", "securities"],
  "industry_types": [],
  "customer_profiles": ["beneficial_owner_obscured"],
  "geographic_footprints": [],
  "regulatory_source": "OFAC Sanctions Advisory: Guidance on Sham Transactions and Sanctions Evasion",
  "regulator": "OFAC",
  "issuing_agencies": [],
  "issued_date": "2026-03-31",
  "risk_level": "medium",
  "category": "sanctions_evasion",
  "typology_family": ["sanctions_evasion"],
  "transaction_patterns": ["third_party_payments", "shell_company_usage"],
  "key_terms": ["blocked person", "sham transaction", "nominal owner", "proxy", "agent-principal"]
}}

## Shared-subject lead-in example

Source excerpt:
"A customer is an individual that:
51. See ICE, News Releases and Statements.
Uses an SSN that, upon verification, does not match or is inconsistent with the SSA's records;
Opens an account using a non-U.S. passport or ITIN claiming to be self-employed or operating a small business in the agriculture, construction, domestic service, hospitality, or staffing industries and is receiving a significant amount and volume of recurring check deposits from multiple companies before either making a significant and repetitive amount of structured cash withdrawals or issuing low-dollar checks to multiple individuals;
Cashes a significant volume of checks drawn on accounts owned by companies in the agriculture, construction, domestic service, hospitality, or staffing industries on a recurring basis at an MSB, including a check cashier;"

The lead-in "A customer is an individual that:" supplies the subject for every bullet. The footnote "51. See ICE, News Releases and Statements." is administrative text and must be ignored without breaking the shared-subject context.

**Wrong** — emitting an orphaned predicate that begins with a bare verb:
{{
  "description": "Uses an SSN that, upon verification, does not match or is inconsistent with the SSA's records"
}}

**Wrong** — extracting the footnote as a red flag:
{{
  "description": "See ICE, News Releases and Statements."
}}

**Correct** — fold the lead-in subject into each bullet so the description is a complete sentence:
{{
  "description": "A customer is an individual that uses an SSN that, upon verification, does not match or is inconsistent with the SSA's records.",
  "product_types": ["depository"],
  "industry_types": [],
  "customer_profiles": ["individual_consumer"],
  "geographic_footprints": ["domestic_us"],
  "regulatory_source": "FinCEN Advisory on Labor Trafficking",
  "regulator": "FinCEN",
  "issuing_agencies": [],
  "issued_date": null,
  "risk_level": "medium",
  "category": "human_trafficking",
  "typology_family": ["human_trafficking_proceeds"],
  "transaction_patterns": ["identity_misrepresentation"],
  "key_terms": ["SSN", "SSA", "identity verification"]
}}

**Correct** — preserve the bullet's qualifying clauses verbatim while folding in the lead-in subject:
{{
  "description": "A customer is an individual that cashes a significant volume of checks drawn on accounts owned by companies in the agriculture, construction, domestic service, hospitality, or staffing industries on a recurring basis at an MSB, including a check cashier.",
  "product_types": ["check_cashing", "money_transmitter"],
  "industry_types": ["agriculture", "construction", "food_service", "travel_hospitality"],
  "customer_profiles": ["individual_consumer", "migrant_worker"],
  "geographic_footprints": ["domestic_us"],
  "regulatory_source": "FinCEN Advisory on Labor Trafficking",
  "regulator": "FinCEN",
  "issuing_agencies": [],
  "issued_date": null,
  "risk_level": "medium",
  "category": "human_trafficking",
  "typology_family": ["human_trafficking_proceeds"],
  "transaction_patterns": ["cash_intensive_behavior", "third_party_payments"],
  "key_terms": ["check cashing", "MSB", "labor-intensive industries"]
}}

## Output format

Return a single JSON object with one key, "red_flags", containing an array of analyzed objects. No markdown fences, no preamble, no commentary — emit valid JSON only. Apply both steps before emitting any entry. Process the entire document; do not stop early."""

    user_prompt = f"""Extract all AML red flags from this regulatory document using the two-step process described.

---
{document_text}
---"""

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


_SHAPING_SYSTEM_PROMPT = """You normalize the grammar of candidate AML red-flag descriptions. Each input is one description, possibly multiple sentences. Rewrite only what is needed; preserve the source's substance and specificity.

## Rules

1. **Noun subject.** The description must begin with a concrete noun subject — for example "Customers," "Entities," "Individuals," "Account holders," "Nominal owners," "Counterparties," "Beneficial owners," or "Transactions". Use "Entities or individuals" when the source could apply to either. If the input already begins with a suitable noun subject, leave it alone. If it begins with a verb phrase or orphaned predicate (e.g., "Are non-responsive..."), add the smallest accurate noun subject and keep the rest of the wording intact ("Entities or individuals are non-responsive...").

2. **Merge dependent explanatory sentences.** When a sentence starting with "Such," "Similarly," "Likewise," "These," "This," or other clearly referential wording elaborates the preceding sentence, merge it into the preceding sentence so the description reads as one indicator. Do not invent new content. Do not merge sentences that introduce a new, independent indicator.

3. **Strip one-off facts.** If named persons, named companies, or one-off case facts slipped through, remove them. Keep generic "for example / e.g. / such as / including" clauses that help define the indicator.

4. **Generalize case-specific numbers and counts.** When a description contains specific dollar amounts, percentages, or quantities drawn from a particular case, rewrite them as generic phrasing and keep the original value as a parenthetical "e.g." example so the indicator becomes reusable. Drop small case-specific counts of entities ("two exchanges", "at least eight variants") entirely — they describe one incident, not a pattern. Examples:
   - "received approximately $100 million in virtual currency stolen from cyber intrusions against two virtual currency exchanges and began layering the funds ... to include purchasing over $1 million in digital music gift cards" → "received large sums (e.g., $100 million) in virtual currency stolen from cyber intrusions against virtual currency exchanges and began layering the funds ... to include purchasing large values (e.g., $1 million) of goods such as digital music gift cards"
   - "Over 40 percent of the exchange's transaction history had been associated with illicit actors, involving the proceeds from at least eight ransomware variants" → "A significant percentage (e.g., 40%) of an exchange's transaction history is associated with illicit actors, involving proceeds from ransomware variants"

   Do not generalize numbers that are part of the indicator's substance (e.g., reporting thresholds like "$10,000", structuring just below "$10,000", "within a 24-hour period") — those define the behavior itself, not a case-specific value.

5. **No other paraphrasing.** Do not generalize, shorten, or reword beyond what rules 1–4 require. If no change is needed, return the input verbatim.

## Output format

Return a single JSON object: {"results": [{"index": 0, "description": "..."}, {"index": 1, "description": "..."}, ...]}

One entry per input, same order, same length. No markdown fences, no commentary — emit valid JSON only."""


def build_shaping_prompt(descriptions: list[str]) -> list[dict]:
    """Build the system and user prompts for shaping candidate descriptions.

    Takes a list of raw extracted descriptions and asks the LLM to
    rewrite each into the project's expected grammar (noun-subject
    leading, dependent-explanatory sentences merged).
    """
    numbered = "\n".join(
        f"[{i}] {desc}" for i, desc in enumerate(descriptions)
    )

    user_prompt = f"""Normalize each candidate description below per the rules.

---
{numbered}
---"""

    return [
        {"role": "system", "content": _SHAPING_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


_CLEAN_SYSTEM_PROMPT = """You are an AML compliance expert reviewing a batch of extracted red flag records. Clean this batch by applying four operations.

## 1. Deduplication

Identify records that describe the same observable indicator as a record appearing earlier in the list. Two records are duplicates when their descriptions describe the same suspicious behavior — even if phrased differently (e.g., past vs. present tense, minor reordering of clauses, "A customer's transactions that did not make economic sense" vs. "A customer's transactions that do not make economic sense"). Records with identical descriptions but different product_types or industry_types are still duplicates at the description level.

Mark the *later* record as the duplicate; keep the earlier one.

## 2. Abbreviation expansion

In the description field of each kept record, expand the first occurrence of each known abbreviation to its full form followed by the abbreviation in parentheses. Only expand when the abbreviation appears in isolation — do not expand when it is already part of a spelled-out phrase in the same description.

| Abbreviation | Expansion |
|---|---|
| CMI | Capital Markets Intermediary (CMI) |
| DPT | Digital Payment Token (DPT) |
| DPTs | Digital Payment Tokens (DPTs) |
| FI | financial institution (FI) |
| CDD | Customer Due Diligence (CDD) |
| BO | beneficial owner (BO) |
| AS | Authorised Signatory (AS) |
| OpCo | operating company (OpCo) |
| OpCos | operating companies (OpCos) |
| L/C | letter of credit (L/C) |
| L/Cs | letters of credit (L/Cs) |
| FATCA | Foreign Account Tax Compliance Act (FATCA) |
| CRS | Common Reporting Standard (CRS) |
| PEP | Politically Exposed Person (PEP) |
| SOW | source of wealth (SOW) |
| SOF | source of funds (SOF) |
| MSB | money services business (MSB) |
| VASP | Virtual Asset Service Provider (VASP) |
| STR | Suspicious Transaction Report (STR) |
| SAR | Suspicious Activity Report (SAR) |
| KYC | Know Your Customer (KYC) |
| AML/CFT | Anti-Money Laundering/Countering the Financing of Terrorism (AML/CFT) |

Do not modify any field other than description.

## 3. Fragment repair

Fix descriptions that are clearly broken:
- If the description begins with a lowercase letter, capitalize it.
- Remove internal document references such as "(through Ext 11)", "(see Table 3)", "(Annex A)", or any parenthetical that references an exhibit, annex, or table by number.
- If the description is a fragment with no grammatical subject (e.g., begins with a bare verb), add the smallest accurate subject. Do not add new content beyond what the description clearly implies.

## 4. Terse descriptions

Keep a terse description when it names a specific, actionable AML signal that a compliance officer would recognize (e.g., "Circular fund flow", "Multiple layers/complex ownership structure", "Nominee arrangements (directors/shareholders)"). Remove only if the description is so generic as to be unactionable (e.g., "Unusual transaction behavior" with no qualifier).

## Output format

Return a single JSON object with one key "records", one entry per input record in the same order:

{
  "records": [
    {"id": "<id>", "keep": true, "description": "<updated or unchanged description>"},
    {"id": "<id>", "keep": false, "duplicate_of": "<id of the earlier record this duplicates>"}
  ]
}

For kept records: always include "description" (updated if a change was needed, otherwise the original verbatim).
For removed duplicates: include "duplicate_of". Omit "description".
No markdown fences, no commentary — emit valid JSON only."""


def build_clean_prompt(records: list[dict]) -> list[dict]:
    """Build system+user prompts to clean a batch of red flag records.

    Handles deduplication, abbreviation expansion, and description repair.
    Only id and description are sent to the model; no metadata is shared.
    """
    numbered = "\n".join(
        f"[{i}] id={r['id']!r}  description={r.get('description', '')!r}"
        for i, r in enumerate(records)
    )

    user_prompt = f"""Clean the following {len(records)} red flag records.

{numbered}"""

    return [
        {"role": "system", "content": _CLEAN_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


OPTIMIZED_PROMPT_PATH = Path(__file__).resolve().parent.parent / "data" / "verifier_prompt.json"

_HANDCRAFTED_SYSTEM_PROMPT = """You are an AML compliance expert reviewing candidate red flags extracted from regulatory documents. Your task is to classify each candidate as a genuine red flag or not.

## What IS a red flag?

A red flag is a description of suspicious, observable behavior by a customer, entity, counterparty, account, ownership/control structure, property, or transaction that a compliance officer or transaction-monitoring system could detect at a financial institution. It indicates potential money laundering, terrorist financing, sanctions evasion, or other financial crime.

A valid red flag answers: "What would a compliance officer or TM analyst actually see at their institution that should raise suspicion?"

## What is NOT a red flag?

- Compliance program guidance, obligations, or controls (what the institution should do)
- Regulatory directives, instructions, or expectations
- SAR filing instructions or recommendations
- Risk assessment frameworks, policies, procedures, training, governance, or audit expectations
- General typology background or educational context that does not describe an observable pattern
- Enforcement action summaries or case narratives that describe what happened to a named person or company without identifying a reusable observable signal
- Document headers, administrative text, or section titles
- Definitions or glossary entries

## Classification rules

For each candidate, answer:
1. Does it describe observable suspicious behavior (what a customer, entity, transaction, account, or property is doing)?
2. Is it reusable — applicable to comparable customers/transactions, not tied to a specific named person or one-off fact?
3. Could a compliance officer or TM system at any financial institution detect this pattern?
4. Does it stand independently and make sense without any additional context ?

If ALL four answers are yes → flag: true
If ANY answer is no → flag: false

## Output format

Return a single JSON object: {"results": [{"index": 0, "flag": true}, {"index": 1, "flag": false}, ...]}

One entry per candidate, in the same order as the input. No markdown fences, no commentary — emit valid JSON only."""


def _load_optimized_prompt() -> dict | None:
    """Load the DSPy-optimized prompt if available."""
    if not OPTIMIZED_PROMPT_PATH.exists():
        return None
    try:
        with open(OPTIMIZED_PROMPT_PATH) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _build_optimized_system_prompt(optimized: dict) -> str:
    """Build system prompt from DSPy-optimized data.

    Uses the optimized instructions and appends few-shot demos.
    """
    instructions = optimized.get("signature", {}).get("instructions", "")
    if not instructions:
        return _HANDCRAFTED_SYSTEM_PROMPT

    demos = optimized.get("demos", [])

    parts = [instructions]

    if demos:
        parts.append("\n## Examples\n")
        for demo in demos:
            desc = demo.get("description", "")
            label = demo.get("is_red_flag", "")
            if isinstance(label, bool):
                label = "true" if label else "false"
            parts.append(f"Description: {desc}\nIs Red Flag: {label}\n")

    parts.append("""
## Output format

Return a single JSON object: {"results": [{"index": 0, "flag": true}, {"index": 1, "flag": false}, ...]}

One entry per candidate, in the same order as the input. No markdown fences, no commentary — emit valid JSON only.""")

    return "\n".join(parts)


def build_verification_prompt(descriptions: list[str], force_handcrafted: bool = False) -> list[dict]:
    """Build the system and user prompts for red-flag verification.

    Takes a list of candidate descriptions and asks the LLM to classify
    each as a genuine red flag (true) or not (false).

    If a DSPy-optimized prompt exists at data/verifier_prompt.json, uses
    that. Otherwise falls back to the handcrafted prompt.

    Pass force_handcrafted=True to always use the handcrafted prompt,
    even when verifier_prompt.json exists (useful for A/B comparison).
    """
    optimized = None if force_handcrafted else _load_optimized_prompt()
    if optimized:
        print("  Using DSPy-optimized verification prompt.")
        system_prompt = _build_optimized_system_prompt(optimized)
    else:
        if force_handcrafted:
            print("  Using handcrafted verification prompt (--prompt handcrafted).")
        system_prompt = _HANDCRAFTED_SYSTEM_PROMPT

    numbered = "\n".join(
        f"[{i}] {desc}" for i, desc in enumerate(descriptions)
    )

    user_prompt = f"""Classify each candidate below as a genuine red flag (true) or not (false).

---
{numbered}
---"""

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
