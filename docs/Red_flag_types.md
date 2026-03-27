# Red Flag Taxonomy by Simulation Data Requirements

**Related:** [[LLM-Based AML Transaction Simulation - Research Notes]]

---

## Overview

This taxonomy organizes red flags by **what data must be simulated** to generate scenarios that satisfy each red flag. The categories are determined by the complexity of the data model required, from simple transaction-only patterns to complex multi-entity networks with external data dependencies.

---

## Taxonomy Summary

| Type | Data Required | Timeframe | Complexity | Example |
|------|---------------|-----------|------------|---------|
| **Type 1: Transaction-Only** | Transactions with attributes | 1-4 weeks | Low | Structuring deposits under $10K |
| **Type 2: Baseline-Relative** | Persona + expected behavior + deviation | 12-26 weeks | Medium | Activity inconsistent with occupation |
| **Type 3: Network/Entity** | Entity graph + ownership + relationships | 2-12 weeks | Medium-High | Shell companies with shared agents |
| **Type 4: Geographic** | Jurisdiction risk data + persona location | 2-12 weeks | Medium | Transfers to secrecy havens |
| **Type 5: Temporal** | Time-series baseline + anomaly phase | 24-52 weeks | Medium | Sudden pattern changes |
| **Type 6: Event-Triggered** | External event + reactive transactions | 4-12 weeks | Medium-High | Transfer after OFAC designation |
| **Type 7: Real-World Grounded** | External data sources (sanctions, news) | 4-52 weeks | High | Connected to sanctioned individuals |
| **Type 8: Out-of-Scope** | Non-transaction data (KYC, documents) | N/A | N/A | Credentials cannot be verified |

---

## Simulation Timeframes

Every red flag simulation requires a **timeframe** specifying how many weeks of transaction history to generate. The timeframe depends on:

1. **Pattern duration** - How long the suspicious activity takes to manifest
2. **Baseline requirements** - Whether a "normal" period is needed for contrast
3. **Detection window** - How much history a TMS typically analyzes

### Timeframe Guidelines by Type

| Type | Typical Timeframe | Minimum | Maximum | Rationale |
|------|-------------------|---------|---------|-----------|
| **1A: Amount-Based** | 1-2 weeks | 1 week | 4 weeks | Structuring patterns are compressed |
| **1B: Data Completeness** | 1-4 weeks | 1 week | 8 weeks | Single transactions or short series |
| **1C: Denomination** | 1-2 weeks | 1 week | 4 weeks | Similar to amount-based |
| **1D: Channel/Instrument** | 1-4 weeks | 1 week | 8 weeks | Deposit-wire sequences |
| **2A: Self-Relative** | 12-26 weeks | 8 weeks | 52 weeks | Need baseline to establish "normal" |
| **2B: Peer-Relative** | 12-26 weeks | 8 weeks | 52 weeks | Need comparison period |
| **2C: Assumed Persona** | 8-16 weeks | 4 weeks | 26 weeks | Shorter if constraints are tight |
| **3A: Shared Attributes** | 2-8 weeks | 1 week | 12 weeks | Coordination can be fast |
| **3B: Network Topology** | 4-12 weeks | 2 weeks | 26 weeks | Layering takes longer |
| **3C: Ownership Structure** | 8-26 weeks | 4 weeks | 52 weeks | Complex fund flows |
| **4A: High-Risk Jurisdiction** | 2-8 weeks | 1 week | 12 weeks | Can be single transactions |
| **4B: Geographic Mismatch** | 4-12 weeks | 2 weeks | 26 weeks | Need pattern of distant activity |
| **5A: Volume/Frequency** | 24-52 weeks | 12 weeks | 104 weeks | 6+ month baseline + anomaly |
| **5B: Pattern Change** | 24-52 weeks | 12 weeks | 104 weeks | Similar to 5A |
| **6: Event-Triggered** | 4-12 weeks | 2 weeks | 26 weeks | Pre-event context + reaction |
| **7: Real-World Grounded** | 4-52 weeks | 4 weeks | 104 weeks | Depends on complexity |

### Default Timeframe Parameter

```python
simulate_red_flag(
    red_flag="Multiple cash deposits under $10K within 5 days",
    timeframe_weeks=2,  # Default varies by type
    ...
)
```

### Timeframe Components for Multi-Phase Types

Some types require distinct phases with separate timeframes:

```
Type 5: Temporal Anomaly
┌─────────────────────────────────────────────────────────┐
│  baseline_weeks: 24    (6 months of "normal" activity)  │
│  anomaly_weeks: 4      (1 month of suspicious activity) │
│  total_weeks: 28                                        │
└─────────────────────────────────────────────────────────┘

Type 6: Event-Triggered
┌─────────────────────────────────────────────────────────┐
│  pre_event_weeks: 4    (context before event)           │
│  post_event_weeks: 2   (reaction window)                │
│  total_weeks: 6                                         │
└─────────────────────────────────────────────────────────┘

Type 2: Baseline-Relative
┌─────────────────────────────────────────────────────────┐
│  baseline_weeks: 12    (establish expected behavior)    │
│  deviation_weeks: 8    (suspicious deviation period)    │
│  total_weeks: 20                                        │
└─────────────────────────────────────────────────────────┘
```

---

## Type 1: Transaction-Only Red Flags

**Typical Timeframe:** 1-4 weeks

### Definition
Red flags that can be satisfied by generating transactions with specific attributes (amount, timing, channel, location) without requiring persona construction, baseline behavior, or entity relationships.

### Data Model Required
```
Transaction:
  - amount: float
  - timestamp: datetime
  - channel: enum (cash, wire, ACH, check)
  - branch/location: string
  - originator: account_id
  - beneficiary: account_id
  - reference/memo: string (optional, can be sparse)
```

### Sub-Types

#### 1A: Amount-Based Patterns
Red flags defined by transaction amounts relative to explicit thresholds.

| Red Flag | Key Attributes | Threshold |
|----------|----------------|-----------|
| Structuring deposits | amount, channel=cash | < $10,000 (CTR threshold) |
| Large cash transactions | amount, channel=cash | > $10,000 |
| Round-dollar amounts | amount | $X,000 exactly |
| Just-under threshold | amount | $9,500-$9,999 range |

**Example:**
> "Multiple cash deposits under $10,000 across different branches within 5 days"

**Simulation approach:** Generate N transactions with amount sampled from Uniform($8,000, $9,900), channel=cash, distributed across M branches, within 5-day window.

#### 1B: Data Completeness Patterns
Red flags defined by missing or sparse transaction fields.

| Red Flag | Missing/Sparse Fields |
|----------|----------------------|
| Minimal originator info | originator_name, originator_address |
| Missing purpose | reference/memo field |
| Incomplete beneficiary | beneficiary_address, beneficiary_bank |

**Example:**
> "Transfers with minimal content and missing party information"

**Simulation approach:** Generate wire transactions with deliberately null/sparse fields:
```
{
  "originator": "ABC LLC",
  "originator_address": null,
  "beneficiary": "XYZ Trading",
  "beneficiary_address": "Hong Kong",
  "purpose": "Services",
  "amount": 847000
}
```

#### 1C: Denomination Patterns (Extended Model)
Red flags requiring denomination breakdown, not just total amounts.

| Red Flag | Denomination Detail |
|----------|---------------------|
| Small-bill deposits | Count of $20s, $50s vs $100s |
| Large-bill turnover | $100 bill exchange patterns |
| Denomination exchange | Small-to-large bill swaps |

**Example:**
> "Deposit of $50,000 in small-denomination bills inconsistent with stated business"

**Simulation approach:** Extend transaction model:
```
{
  "amount": 50000,
  "denomination_breakdown": {
    "$20": 2500,
    "$50": 0,
    "$100": 0
  }
}
```

**Note:** Denomination patterns require extending the base transaction model.

#### 1D: Channel/Instrument Patterns
Red flags defined by the payment channel or instrument used.

| Red Flag | Channel Attribute |
|----------|-------------------|
| Cash followed by wire | Sequence: cash deposit → wire out |
| Cashier's check purchases | instrument=cashier_check |
| Cryptocurrency conversion | channel=crypto_exchange |

**Example:**
> "Large currency deposits followed by immediate wire transfers"

**Simulation approach:** Generate transaction sequences with specified channel transitions and timing constraints.

---

## Type 2: Baseline-Relative Red Flags

**Typical Timeframe:** 12-26 weeks (baseline period + deviation period)

### Definition
Red flags that describe deviations from expected behavior. Requires constructing a persona with baseline characteristics, then generating transactions that deviate from those expectations.

### Data Model Required
```
Persona:
  - occupation: string
  - employer_type: string (NPO, corporate, self-employed)
  - income_level: float (annual)
  - residence_location: geography
  - work_location: geography
  - business_type: string (if applicable)
  - expected_transaction_pattern: distribution

Transaction:
  - (all Type 1 fields)
  - linked to persona

Deviation:
  - actual_pattern vs expected_pattern
```

### Sub-Types

#### 2A: Self-Relative Baselines
Deviation from the individual's own expected behavior based on their stated attributes.

| Red Flag | Persona Attributes | Deviation |
|----------|-------------------|-----------|
| Activity inconsistent with occupation | occupation, income | Deposits >> expected income |
| Unaffiliated geography | residence, work location | Activity in distant locations |
| Business type mismatch | business_type, products | Transactions inconsistent with business |

**Example:**
> "Activity inconsistent with stated occupation"

**Simulation approach:**
1. Construct persona: Restaurant worker, age 28, expected income ~$35K/year
2. Generate expected baseline: Small purchases, biweekly deposits ~$1,200
3. Generate deviation: $8K-$9K cash deposits weekly = ~$450K/year

```
Two-Phase Generation
┌─────────────────────────────────────────────────────────┐
│  Phase 1: Baseline Construction                         │
│  • Persona: John Smith, accountant, Newark NJ           │
│  • Expected deposits: Payroll ($4K biweekly)            │
│  • Expected spending: Typical consumer pattern          │
│  • "Affiliated" geography: NJ, NYC metro                │
├─────────────────────────────────────────────────────────┤
│  Phase 2: Deviation Generation                          │
│  • Actual deposits: $8K cash from Miami, Phoenix        │
│  • Depositors: Unrelated individuals                    │
│  • Pattern: Inconsistent with accountant profile        │
└─────────────────────────────────────────────────────────┘
```

#### 2B: Peer-Relative Baselines
Deviation from what similar entities (peer group) typically do.

| Red Flag | Peer Group Definition | Deviation |
|----------|----------------------|-----------|
| Greater deposits than peers | Same profession, region, size | Statistical outlier |
| Cash ratio anomaly | Same business type | Higher cash % than peers |
| Transaction frequency anomaly | Similar account type | More frequent than peers |

**Example:**
> "A customer making significantly greater deposits than those of peers in similar professions"

**Simulation approach:**
1. Construct persona: Small restaurant owner, Queens NY, 15 employees
2. Synthesize peer group behavior using LLM world knowledge:
   - Typical monthly deposits: $50K-$80K
   - Cash ratio: 30-40%
3. Generate deviation: $180K monthly deposits, 70% cash ratio

**Why LLM-enabled:** Agent reasons about peer group characteristics without explicit lookup tables.

#### 2C: Assumed Persona Constraints
Red flag text specifies persona attributes that must be constructed (not searched).

| Red Flag | Assumed Attributes |
|----------|-------------------|
| Government benefit recipient | Benefits enrollment (SNAP, etc.) |
| NPO employee | Employer type = nonprofit |
| Specific occupation | Occupation stated in red flag |

**Example:**
> "A customer is an employee of a company or NPO enrolled in a government benefit program that is frequently purchasing cashier's checks"

**Simulation approach:**
1. Extract constraints from red flag: NPO employee + benefits enrollment
2. Construct persona with those attributes
3. Infer related attributes: Low income (~$35K), modest expected transactions
4. Generate deviation: Frequent cashier's check purchases ($2K-$5K each)

---

## Type 3: Network/Entity Red Flags

**Typical Timeframe:** 2-12 weeks (longer for complex layering)

### Definition
Red flags where the suspicion is in the **structural relationships** between entities, not just individual transactions. Requires constructing a multi-entity graph with shared attributes or coordination patterns.

### Data Model Required
```
Entity:
  - type: enum (person, company, trust)
  - name: string
  - address: geography
  - phone: string
  - registered_agent: string (for companies)
  - beneficial_owner: entity_id

Account:
  - owner: entity_id
  - bank: institution_id
  - type: enum (personal, business)

Ownership_Edge:
  - owner: entity_id
  - owned: entity_id
  - ownership_percentage: float

Transaction:
  - (all Type 1 fields)
  - linked to accounts/entities
```

### Sub-Types

#### 3A: Shared Attribute Patterns
Multiple entities sharing attributes that suggest hidden coordination.

| Red Flag | Shared Attribute |
|----------|-----------------|
| Shared addresses | address |
| Shared phone numbers | phone |
| Shared registered agent | registered_agent |
| Common beneficial owner | beneficial_owner |

**Example:**
> "Persons in currency transactions sharing addresses/phone numbers"

**Simulation approach:**
1. Create N personas (e.g., 5 individuals)
2. Assign shared attributes: 2 addresses shared across all 5
3. Generate structuring transactions from each persona
4. The coordination signal is in the entity graph, not just transactions

```
Entity Graph with Shared Attributes
┌─────────────────────────────────────────────────────────┐
│  Person A ─┬─ Address: 123 Main St                      │
│  Person B ─┤                                            │
│  Person C ─┘                                            │
│                                                         │
│  Person D ─┬─ Address: 456 Oak Ave                      │
│  Person E ─┘                                            │
│                                                         │
│  All 5 → Cash deposits → Same beneficiary account       │
└─────────────────────────────────────────────────────────┘
```

#### 3B: Network Topology Patterns
Red flags defined by the shape of the transaction network.

| Red Flag | Topology |
|----------|----------|
| Fan-in | Many senders → one beneficiary |
| Fan-out | One sender → many beneficiaries |
| Layering | Chain: A → B → C → D |
| Round-trip | A → B → ... → A |

**Example:**
> "Multiple accounts funneling to a small number of foreign beneficiaries"

**Simulation approach:**
1. Create M source accounts (domestic)
2. Create N sink accounts (foreign, N << M)
3. Generate transactions creating fan-in topology
4. The network structure IS the red flag

#### 3C: Ownership Structure Patterns
Red flags involving shell companies, trusts, and beneficial ownership.

| Red Flag | Ownership Pattern |
|----------|-------------------|
| Shell company network | Company X owns Company Y, shared agent |
| Trust purchases | Trust → real estate, obscured beneficiary |
| Layered ownership | Person → Company → Company → Account |

**Example:**
> "The use of legal entities or arrangements, such as trusts, to purchase CRE"

**Simulation approach:**
1. Construct ownership graph:
   - Person A owns Company X (Wyoming)
   - Company X owns Company Y (Delaware)
   - Company Y has bank account
2. Generate transactions: Funds flow through chain, purchase CRE
3. Output includes both transactions and ownership graph

---

## Type 4: Geographic Risk Red Flags

**Typical Timeframe:** 2-12 weeks

### Definition
Red flags involving high-risk jurisdictions or geographic anomalies between persona location and transaction activity.

### Data Model Required
```
Jurisdiction_Risk:
  - country: string
  - risk_level: enum (high, medium, low)
  - risk_lists: [FATF_grey, FATF_black, secrecy_index]

Persona:
  - (Type 2 fields)
  - residence_country: string
  - work_country: string

Transaction:
  - (Type 1 fields)
  - originator_country: string
  - beneficiary_country: string
```

### Sub-Types

#### 4A: High-Risk Jurisdiction Transfers
Transactions to/from countries on risk lists.

| Red Flag | Risk Criterion |
|----------|---------------|
| Secrecy haven transfer | FATF grey/black list, secrecy index |
| Sanctioned jurisdiction | OFAC sanctions |
| Tax haven routing | Low-tax jurisdictions without business purpose |

**Example:**
> "Transfers to financial secrecy havens without business reason"

**Simulation approach:**
1. Query jurisdiction risk list (tool: `lookup_jurisdiction_risk`)
2. Generate wire transfers to high-risk destinations
3. Ensure no legitimate business purpose in reference field

#### 4B: Geographic Mismatch Patterns
Activity location inconsistent with persona's stated geography.

| Red Flag | Mismatch Type |
|----------|--------------|
| Distant bank use | Banking far from residence/business |
| Unaffiliated deposits | Deposits from distant locations |
| Travel pattern anomaly | Activity in unusual locations |

**Example:**
> "Geographically distant bank use without business purpose"

**Simulation approach:**
1. Construct persona: Residence in Newark NJ, business in Jersey City
2. Generate activity: All banking in Miami, no business connection to Florida
3. The geographic mismatch IS the red flag

---

## Type 5: Temporal Anomaly Red Flags

**Typical Timeframe:** 24-52 weeks (long baseline required for contrast)

### Definition
Red flags describing sudden changes in transaction patterns over time. Requires generating a baseline period followed by an anomaly phase.

### Data Model Required
```
Timeline:
  - baseline_period: date_range
  - anomaly_period: date_range

Baseline_Pattern:
  - transaction_volume: distribution
  - transaction_frequency: distribution
  - typical_amounts: distribution

Anomaly_Pattern:
  - deviation_from_baseline: comparison
```

### Sub-Types

#### 5A: Volume/Frequency Anomalies
Sudden increase in transaction activity.

| Red Flag | Anomaly Type |
|----------|-------------|
| Sudden deposit increase | Volume jumps 5-10x |
| Frequency spike | Daily transactions vs weekly |
| New account burst | High activity shortly after opening |

**Example:**
> "Sudden currency transaction pattern changes"

**Simulation approach:**
1. Generate 6 months of baseline: ~$5K deposits/month, biweekly
2. Generate anomaly phase: $50K deposits/month, daily
3. The contrast between phases IS the red flag

```
Temporal Anomaly Pattern
┌─────────────────────────────────────────────────────────┐
│  Baseline Period (6 months)                             │
│  • Monthly deposits: $5K                                │
│  • Frequency: Biweekly payroll                          │
│  • Pattern: Consistent with persona                     │
├─────────────────────────────────────────────────────────┤
│  Anomaly Period (1 month)                               │
│  • Monthly deposits: $50K                               │
│  • Frequency: Daily cash deposits                       │
│  • Pattern: Sudden 10x increase                         │
│                                                         │
│  The CONTRAST is the red flag                           │
└─────────────────────────────────────────────────────────┘
```

#### 5B: Pattern Change Without Business Justification
Changes that don't correlate with legitimate business events.

| Red Flag | What's Missing |
|----------|---------------|
| No business expansion | Deposits up, no new revenue source |
| No seasonal explanation | Change outside normal seasonality |
| No life event | No marriage, inheritance, sale |

**Example:**
> "Rapid increase in currency deposits without noncurrency growth"

**Simulation approach:**
1. Generate baseline with stable card transactions (business revenue proxy)
2. Generate cash deposit spike with no corresponding card increase
3. The asymmetry between cash and card IS the red flag

---

## Type 6: Event-Triggered Red Flags

**Typical Timeframe:** 4-12 weeks (pre-event context + post-event reaction)

### Definition
Red flags describing reactive behavior triggered by external events (arrests, sanctions, legal actions). Requires simulating the event and temporally-linked reactive transactions.

### Data Model Required
```
External_Event:
  - type: enum (arrest, OFAC_designation, indictment, sanctions)
  - target: entity_id
  - date: datetime

Reactive_Transaction:
  - transaction: Transaction
  - triggering_event: External_Event
  - temporal_proximity: duration
```

### Key Pattern

```
Event-Triggered Pattern
┌─────────────────────────────────────────────────────────┐
│  External Event                 Reactive Behavior       │
│  ┌─────────────┐               ┌─────────────────────┐ │
│  │ OFAC        │               │ Transfer assets to  │ │
│  │ designation │ ── triggers ──│ family member       │ │
│  │ (Day 0)     │               │ (Day 2)             │ │
│  └─────────────┘               └─────────────────────┘ │
│                                                         │
│  The TIMING is the red flag                             │
└─────────────────────────────────────────────────────────┘
```

**Example:**
> "Transfers of assets from a PEP or Russian elite to a family member in close temporal proximity to a legal event such as an arrest or an OFAC designation"

**Simulation approach:**
1. Establish entity: PEP or connected individual
2. Inject external event: OFAC designation on Day 0
3. Generate reactive transfer: $10M to family trust on Day 2
4. The temporal proximity IS the red flag

**Distinction from Type 5 (Temporal Anomaly):**
- Type 5: Internal pattern change (sudden increase)
- Type 6: External event triggers reaction (arrest → transfer)

---

## Type 7: Real-World Grounded Red Flags

**Typical Timeframe:** 4-52 weeks (varies by complexity of entity network)

### Definition
Red flags that require grounding in actual real-world entities, not fictional personas. Requires searching external data sources.

### Data Model Required
```
External_Data_Sources:
  - sanctions_lists: [OFAC, EU, UN]
  - PEP_databases: [various]
  - corporate_registries: [state filings, beneficial ownership]
  - news_sources: [investigative journalism, enforcement actions]
  - leaked_databases: [Panama Papers, Pandora Papers]

Real_World_Entity:
  - name: string
  - sanctions_status: boolean
  - known_associates: [entity_id]
  - family_members: [entity_id]
  - shell_companies: [entity_id]
  - previous_activity: [transactions, properties]
```

### Agent Tools Required

| Tool | Purpose |
|------|---------|
| `search_sanctions(name, list)` | Query OFAC, EU, UN sanctions lists |
| `web_search(query)` | Find news, investigations, leaked documents |
| `search_corporate_records(entity)` | Find beneficial ownership, registered agents |
| `lookup_pep_status(name)` | Check PEP databases |

### Example Red Flags

| Red Flag | External Data Needed |
|----------|---------------------|
| Connected to sanctioned individuals | Sanctions list + associate network |
| PEP relationships | PEP database + family/associate links |
| Shell company in leaked papers | Panama/Pandora Papers |

**Example:**
> "The use of legal entities to purchase CRE that involves friends, associates, family members, or others with a close connection to sanctioned Russian elites"

**Simulation approach:**
1. Search OFAC sanctions list for Russian elites
2. Search news/leaks for known associates, family members
3. Search corporate records for shell companies
4. Construct network: Oligarch X → Associate Y → Trust Z
5. Generate transactions: Trust Z purchases Miami CRE
6. The real-world connection IS the red flag

**Ethical consideration:** Scenarios involving real sanctioned individuals require appropriate use disclaimers and may be limited to authorized research contexts.

---

## Type 8: Out-of-Scope (Non-Simulatable) Red Flags

### Definition
Red flags that cannot be simulated as transaction patterns because they involve:
- Document verification processes
- KYC/due diligence procedures
- Employee behavior or internal controls
- Trade documents (invoices, shipping records)
- Customer interactions or refusals

### Why Out-of-Scope
These red flags describe **operational controls**, not financial transaction flows. A transaction simulator cannot generate:
- Whether credentials can be verified
- Whether a customer refuses to provide information
- Whether an employee has unexplained wealth
- Whether invoice prices match market value

### Categories

| Category | Example Red Flag | Why Non-Simulatable |
|----------|-----------------|---------------------|
| **Document/KYC** | "Credentials cannot be verified" | Requires verification process |
| **Adverse Media** | "Subject of adverse media" | External reputation check |
| **Process-Based** | "Customer refuses to provide information" | Customer interaction |
| **Employee/Insider** | "Lavish lifestyle unsupported by salary" | Internal HR data |
| **TBML (Trade Docs)** | "Over-invoicing" | Requires invoice vs market value |

### Agent Behavior for Out-of-Scope Inputs

```
User: Simulate "ERC obtained by firm whose credentials cannot be verified"

Agent: This red flag cannot be simulated because it involves:
  • Document verification processes
  • Third-party credential checks
  • KYC/due diligence procedures

These are not transaction patterns. This system simulates
financial transaction flows, not document/process controls.

Would you like to provide a transaction-based red flag instead?
```

### Partial Scope: TBML

Trade-Based Money Laundering (TBML) red flags have mixed simulatability:

| TBML Element | Simulatable? | Notes |
|--------------|--------------|-------|
| Payment to high-risk jurisdiction | **Yes** | Wire destination |
| Counterparty sanctions connection | **Yes** | Beneficiary screening |
| Round-trip payment flows | **Yes** | Transaction patterns |
| Over/under-invoicing | **No** | Requires invoice data |
| Goods don't match shipment | **No** | Requires customs data |

For Phase 1, focus on payment-layer TBML patterns only.

---

## Implementation Priority

Based on complexity and value for prototype:

| Priority | Type | Timeframe | Rationale |
|----------|------|-----------|-----------|
| **P1** | Type 1 (Transaction-Only) | 1-4 weeks | Simplest to implement, classic patterns |
| **P2** | Type 2A (Self-Relative) | 12-26 weeks | Tests LLM persona construction |
| **P2** | Type 3A (Shared Attributes) | 2-8 weeks | Tests entity graph construction |
| **P3** | Type 5A (Temporal Anomaly) | 24-52 weeks | Tests two-phase generation |
| **P3** | Type 4A (High-Risk Jurisdiction) | 2-8 weeks | Tests external data lookup |
| **P4** | Type 2B (Peer-Relative) | 12-26 weeks | Tests LLM world knowledge |
| **P4** | Type 6 (Event-Triggered) | 4-12 weeks | Tests event simulation |
| **P5** | Type 7 (Real-World Grounded) | 4-52 weeks | Requires external APIs |
| **N/A** | Type 8 (Out-of-Scope) | N/A | Not implementable |

---

## Suggested Prototype Red Flags

For each type, a good first test case:

| Type | Suggested Red Flag | Timeframe | Why Good for Testing |
|------|-------------------|-----------|---------------------|
| **1A** | "Multiple cash deposits under $10K within 5 days" | 1-2 weeks | Classic structuring, well-defined |
| **1B** | "Wire transfer with missing originator address" | 1 week | Simple field omission |
| **2A** | "Activity inconsistent with stated occupation" | 16 weeks | Tests persona + deviation |
| **2B** | "Greater deposits than peers in similar profession" | 16 weeks | Tests LLM peer reasoning |
| **3A** | "Persons sharing addresses in currency transactions" | 4 weeks | Tests entity graph |
| **3B** | "Multiple accounts funneling to single beneficiary" | 8 weeks | Tests fan-in topology |
| **4A** | "Wire to financial secrecy haven without business purpose" | 4 weeks | Tests jurisdiction lookup |
| **5A** | "Sudden increase in cash deposits" | 28 weeks | Tests baseline + anomaly |
| **6** | "Asset transfer shortly after OFAC designation" | 6 weeks | Tests event + reaction |
| **7** | "Connected to sanctioned Russian elite" | 12 weeks | Tests real-world grounding |

---

## Cross-Reference: Red Flag → Type Mapping

| Red Flag Category (from FFIEC) | Primary Type(s) |
|-------------------------------|-----------------|
| Structuring | Type 1A |
| Funds Transfers | Type 1D, Type 4A |
| Unusual Activity | Type 2A, Type 2B, Type 5A |
| Geographic Concerns | Type 4A, Type 4B |
| Shell Companies | Type 3C |
| Network Patterns | Type 3A, Type 3B |
| PEP/Sanctions | Type 7 |
| Data Quality | Type 1B |
| TBML | Type 1D (partial), Type 8 (trade docs) |

---

## References

- [[LLM-Based AML Transaction Simulation - Research Notes]] - Full research context
- [FFIEC BSA/AML Manual - Red Flags](https://bsaaml.ffiec.gov/manual/Appendices/07) - Source of red flag definitions
