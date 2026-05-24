"""Prompt templates for LLM-based extraction."""

from __future__ import annotations

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

**Where to look when no explicit section exists:** If the document has no explicit red-flag, risk-factor, or indicator section, scan the entire document. Indicators may appear in narrative form within typology descriptions, advisories, and case discussions — extract those only when they pass the observability and reusable-indicator tests.

**Reusable-indicator test:** A valid red flag must be generally applicable to comparable customers, transactions, counterparties, accounts, or property. It must not depend on an actual named person, named company, enforcement target, or one-off historical fact. Do not extract named persons, named companies, enforcement targets, or one-off factual examples as red flags. If a case example illustrates a generic indicator, extract the generic indicator only when the document itself supports that generic wording.

**Compliance guidance exclusion:** Do not extract institutional compliance obligations, program components, control expectations, risk assessment processes, policies, procedures, training, governance, audit/testing, remediation, recordkeeping, escalation, reporting, or sanctions compliance framework elements. These describe what the regulated organization should do, not suspicious activity by a customer, entity, transaction, account, counterparty, ownership/control structure, or property. A compliance framework document can validly produce zero red flags when it lacks distinct suspicious-activity indicators.

**Handling embedded examples:** When a generic indicator inside the eligible extraction area is followed by an example clause introduced by "for example," "e.g.,", "such as," or "including," keep the example only if it remains generic and helps define the indicator. Do not extract illustrative case examples as standalone red flags. Do not include actual names or one-off facts from examples.

**Handling indicators embedded in prose:** When an indicator appears within a longer sentence ("Among the patterns observed are X, Y, and Z"), extract the indicator clause itself with its exact wording preserved. Do not paraphrase or generalize.

**Description subject grammar:** Descriptions must begin with a noun subject, not a verb or orphaned predicate. Prefer a concrete source-supported subject such as "Customers," "Entities," "Individuals," "Account holders," "Nominal owners," "Counterparties," or "Transactions". Use "Entities or individuals" when the source could apply to either. If the source wording starts with a verb phrase or predicate, add the smallest accurate noun subject and keep the rest of the source wording intact.

**Dependent explanatory sentences:** Do not extract dependent explanatory sentences as standalone red flags when they merely explain, elaborate, or refer back to a preceding indicator. Sentences beginning with "Such," "Similarly," "Likewise," "These," "This," or similar referential wording usually depend on the previous sentence. Merge them into the previous indicator only when they are generic, inside an eligible extraction area, and necessary to preserve the indicator's meaning.

**Implicit red flags in case narratives:** Use implicit red flag extraction only when the document has no explicit red-flag, risk-factor, or indicator section. Regulators often describe control failures, execution lapses, alert-review findings, or case examples without labeling the underlying signal as a red flag. Extract the reusable observable customer behavior, transaction-monitoring signal, adverse-news signal, discrepancy, or CDD/risk-assessment conflict when the narrative shows that it should have raised suspicion. For example, if a regulator says an FI failed to escalate "the discrepancy in Customer G's business activity between the FI's records and corporate registry," extract that generic discrepancy as the red flag. Preserve the source wording as much as possible, but extract the observable signal rather than the institution's failure to act. When an explicit section exists, ignore narrative examples, typology examples, enforcement narratives, and case studies outside that section.

**Do NOT extract:**
- Anything outside an explicit red-flag, risk-factor, or indicator section when the document has such a section
- Actual named persons, named companies, enforcement targets, or one-off factual examples
- Compliance program guidance, sanctions compliance framework commitments, internal controls, risk assessments, training, governance, audit/testing, remediation, recordkeeping, escalation, reporting, policies, or procedures
- Enforcement actions, historical case summaries, or descriptions of past violations when they do not contain a reusable observable customer or transaction signal
- SAR filing instructions or recommendations
- Regulatory directives or institutional compliance obligations
- General typology explanations that do not describe an observable pattern
- Document headers, section titles, introductory text, administrative text

Enforcement actions and historical cases are excluded only when they describe institutional failures without a reusable observable red flag and the document has no explicit indicator section. If there is no explicit section and the same passage identifies suspicious customer activity, TM alerts, adverse news, inconsistencies between public records and FI records, or discrepancies that should trigger CDD/risk review, extract the reusable observable signal and exclude only the institutional lapse language.

**Test before including:** Could a compliance officer or TM system at a financial institution directly observe this for any comparable customer, rather than only for a named person or historical target? If no, exclude it.

**Deduplication:** Some indicators appear in multiple sections (e.g., an executive summary up front and a detailed section later). Extract each distinct indicator once. Two passages refer to the same indicator if they describe the same observable pattern, even when worded differently — keep the more specific version.

## Step 2 — Analyze each red flag

For each indicator identified in Step 1, populate the following fields:

- "description" (string, required): The indicator's wording from the source, including any generic embedded example clause needed to define the indicator. No truncation. If the indicator is embedded mid-sentence, extract the indicator clause itself with its wording preserved, but ensure it begins with a noun subject. Do not include actual names or one-off case facts. If a narrative document lacks an explicit indicator section, extract the reusable observable signal rather than institutional failure language.

- "product_types" (list of strings): Financial products or channels offered by the institution that this indicator applies to. Prefer these values when applicable: {sorted(PRODUCT_TYPES)}. Include all that apply. This field is about the institution's product surface, not about who the customer is — customer-side institution categories such as "money transmitter" or "MSB" belong in industry_types.

- "industry_types" (list of strings): Customer industries or business sectors involved. Prefer these values when applicable: {sorted(INDUSTRY_TYPES)}. Empty list when no industry is implied.

- "customer_profiles" (list of strings): Customer archetypes involved. Prefer these values when applicable: {sorted(CUSTOMER_PROFILES)}. Empty list when no profile is implied.

- "geographic_footprints" (list of strings): Geographies, corridors, or regional footprints involved. Prefer these values when applicable: {sorted(GEOGRAPHIC_FOOTPRINTS)}. Empty list when none is implied.

- "regulatory_source" (string): Full name of the issuing document or authority (e.g., "FinCEN Alert FIN-2022-Alert001", "FFIEC BSA/AML Examination Manual Appendix F").

- "regulator" (string): Abbreviated name of the issuing regulatory authority. Choose from: {sorted(REGULATORS)}. Use null when the issuing authority is not represented in the list or cannot be identified from the document.

- Do not emit regulator_jurisdiction. It is assigned deterministically by code from the extracted regulator after validation.

- "issued_date" (string): Publication date of the issuing document in ISO 8601 format (YYYY-MM-DD). Use YYYY-MM if only the month is known, YYYY if only the year is known. Use null if the date cannot be determined from the document.

- "risk_level" (string): Standalone inferential strength of this indicator — how much suspicion the indicator alone justifies before corroboration. One of: {sorted(RISK_LEVELS)}.
  - "high": indicator alone justifies investigation; specific behavior tightly coupled to a known typology or sanctions violation
  - "medium": suspicious pattern that warrants investigation but typically requires corroboration
  - "low": weak signal; meaningful only when combined with other indicators

  Do not infer risk_level from the typology category. A generic structuring or sanctions reference is not automatically "high" — anchor on how specific and self-contained the observable behavior is.

- "category" (string): Primary AML typology. Choose from: {sorted(CATEGORIES)}. When multiple apply, choose the one most specific to the observable behavior described, not the broadest.

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
  "issued_date": "2022-06",
  "risk_level": "high",
  "category": "sanctions_evasion"
}}

## Description grammar example

Source: "Are non-responsive or refuse to provide additional transaction information in response to a virtual currency company's request."

**Wrong** — begins with a verb phrase:
{{
  "description": "Are non-responsive or refuse to provide additional transaction information in response to a virtual currency company's request."
}}

**Correct** — adds the smallest accurate noun subject:
{{
  "description": "Entities or individuals are non-responsive or refuse to provide additional transaction information in response to a virtual currency company's request.",
  "product_types": ["virtual_assets"],
  "industry_types": [],
  "customer_profiles": [],
  "geographic_footprints": [],
  "regulatory_source": "Virtual currency sanctions compliance guidance",
  "regulator": null,
  "issued_date": null,
  "risk_level": "medium",
  "category": "sanctions_evasion"
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
  "issued_date": null,
  "risk_level": "medium",
  "category": "customer_due_diligence"
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
  "issued_date": "2026-03-31",
  "risk_level": "medium",
  "category": "sanctions_evasion"
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
  "issued_date": "2026-03-31",
  "risk_level": "medium",
  "category": "sanctions_evasion"
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
