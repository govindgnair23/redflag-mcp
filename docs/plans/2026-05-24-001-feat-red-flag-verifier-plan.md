---
title: "feat: Add red flag verifier with DSPy optimization"
type: feat
status: active
date: 2026-05-24
origin: docs/brainstorms/2026-05-24-red-flag-verifier-requirements.md
---

# feat: Add red flag verifier with DSPy optimization

## Overview

Add a second-stage LLM verification step to the extraction pipeline that classifies each candidate red flag as genuine (True) or false positive (False). Use DSPy to optimize the verifier prompt against a labelled dataset. Also refactor prompts into a separate module, and add deterministic regulator inference from source URLs.

## Problem Frame

The extraction prompt in `scripts/extract.py` produces a 59% false positive rate (53/90 items in the labelled dataset). Document 048 (OFAC compliance framework) alone contributed 45 false positives with zero valid red flags. The prompt already contains extensive exclusion instructions, but has reached diminishing returns on instruction complexity. A post-extraction verification step is needed. (see origin: `docs/brainstorms/2026-05-24-red-flag-verifier-requirements.md`)

## Requirements Trace

- R1. Verifier step: second LLM call classifies each item as `flag: True/False`
- R2. Description-only input to verifier
- R3. Eval script reporting precision, recall, F1, confusion matrix
- R4. DSPy prompt optimization against labelled dataset
- R5. Integration into `process_one()` with `--no-verify` flag
- R6. Batch verification (minimize API calls)
- R7. Move prompts to separate module
- R8. Regulator inference from source URL domain

## Scope Boundaries

- Not changing the first-stage extraction prompt
- No LangGraph or multi-agent framework
- No model fine-tuning
- No UI or human-in-the-loop

## Context & Research

### Relevant Code and Patterns

- `scripts/extract.py` — extraction pipeline; `build_extraction_prompt()` at line 236 builds inline prompts; `process_one()` at line 592 is the integration point; `validate_and_build_entries()` at line 510 handles validation
- `src/redflag_mcp/config.py` — `REGULATORS`, `REGULATOR_JURISDICTIONS`, `jurisdiction_for_regulator()` already exist for regulator lookups
- `tests/test_extract.py` — comprehensive tests for extraction prompt, validation, manifest, slugs
- `data/source/labelled/*.yaml` — 5 files, 90 items (35 True, 53 False), each entry has `flag: True/False` alongside standard RedFlagSource fields

### External References — DSPy 2.x

- **Binary classification**: `dspy.Predict('description -> is_red_flag: bool')` or class-based `dspy.Signature` with `bool` output field. DSPy handles prompt engineering and type coercion.
- **Optimizer choice**: `MIPROv2` jointly optimizes instructions + few-shot demos using Bayesian optimization. `BootstrapFewShot` is simpler but only selects demos. For 90 labelled examples, **`BootstrapFewShot` is the practical starting point** — MIPROv2 requires more API calls and is better as a second-pass upgrade.
- **OpenAI config**: `dspy.LM("openai/gpt-4o-mini")` — DSPy uses litellm under the hood.
- **Structured output**: DSPy's `JSONAdapter` supports structured output with OpenAI models. Bool output fields work natively.
- **Batch processing**: DSPy operates **item-by-item** — there is no single-call batch mode. `dspy.Parallel(num_threads=N)` enables concurrent per-item calls. This conflicts with R6's goal of a single batched LLM call.
- **Save/load**: `program.save("path.json")` / `Program.load("path.json")` — saves optimized instructions + demos as JSON. Prefer JSON over pickle.
- **Python**: Requires 3.10+; compatible with 3.11.

### Domain-to-Regulator Mapping (from source URL audit)

```
ofac.treasury.gov     → OFAC
home.treasury.gov     → OFAC
www.fincen.gov        → FinCEN
bsaaml.ffiec.gov      → FFIEC
www.ic3.gov           → FBI
www.irs.gov           → IRS
www.finra.org         → FINRA
fintrac-canafe.canada.ca → FINTRAC
www.handbook.fca.org.uk  → FCA
www.nationalcrimeagency.gov.uk → NCA (not in current REGULATORS set)
assets.publishing.service.gov.uk → OFSI (not in current REGULATORS set)
www.gov.uk            → OFSI
www.eba.europa.eu     → EBA
www.europol.europa.eu → Europol
www.afm.nl            → AFM (maps to FIU-NL or new entry)
www.mas.gov.sg        → MAS
www.hkma.gov.hk       → HKMA
www.sfc.hk            → SFC-HK
www.jfiu.gov.hk       → JFIU (Hong Kong)
www.npa.go.jp         → JFSA (or NPA)
www.austrac.gov.au    → AUSTRAC
www.fatf-gafi.org     → FATF
www.centralbank.ae    → CBUAE (new)
rulebook.centralbank.ae → CBUAE
www.sama.gov.sa       → SAMA (new)
www.rbi.org.in        → RBI (new)
```

## Key Technical Decisions

- **DSPy for optimization, raw OpenAI for production verification**: DSPy operates item-by-item. For production use (R6 batch verification), the verifier will use a direct OpenAI API call with the optimized prompt, classifying all items from one document in a single call. DSPy is used only in the optimization script to find the best prompt/demos. The optimized prompt is then exported and used directly.
- **BootstrapFewShot first, MIPROv2 later**: Start with the simpler optimizer. 90 examples is enough for few-shot demo selection. MIPROv2 can be tried as an upgrade if BootstrapFewShot underperforms.
- **Prompts module placement**: `scripts/prompts.py` — keeps it with the extraction scripts rather than in `src/redflag_mcp/` (which is the MCP server package, not the extraction pipeline). The extraction prompt and verification prompt are both script-side concerns.
- **Domain-to-regulator mapping in config.py**: Add `URL_DOMAIN_TO_REGULATOR` dict alongside existing `REGULATORS`/`REGULATOR_JURISDICTIONS`. This keeps all regulator logic centralized.
- **Eval script as standalone**: `scripts/eval_verifier.py` runs the verifier against labelled data and reports metrics. Also reports extraction-only baseline for comparison (R3 deferred question — yes, include baseline).

## Open Questions

### Resolved During Planning

- **Which DSPy optimizer?** → `BootstrapFewShot` first, upgrade to `MIPROv2` if needed.
- **Batch vs item-by-item?** → DSPy is item-by-item. Production verifier uses direct OpenAI call with optimized prompt for batching. DSPy optimizes the prompt offline.
- **Include baseline in eval?** → Yes. Eval script reports both extraction-only and extraction+verifier metrics.
- **Full domain mapping?** → Audit complete (see above). ~25 mappable domains. Some need new REGULATORS entries (NCA, OFSI, CBUAE, SAMA, RBI).

### Deferred to Implementation

- Exact threshold for DSPy optimization convergence — depends on running it
- Whether `ChainOfThought` (reasoning before classification) outperforms `Predict` (direct classification) — try both during optimization
- How to handle domains that map to multiple possible regulators (e.g., `assets.publishing.service.gov.uk` could be OFSI or other UK gov bodies) — start with most common mapping, refine as edge cases appear

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification. The implementing agent should treat it as context, not code to reproduce.*

```
┌──────────────────────────────────────────────────────────────────┐
│                    OFFLINE (one-time)                             │
│                                                                  │
│  data/source/labelled/*.yaml                                     │
│         │                                                        │
│         ▼                                                        │
│  scripts/optimize_verifier.py                                    │
│    ┌─ dspy.BootstrapFewShot ─┐                                   │
│    │  Signature: desc → bool │                                   │
│    │  Train on labelled data │                                   │
│    └─────────────────────────┘                                   │
│         │                                                        │
│         ▼                                                        │
│  data/verifier_prompt.json  (optimized instructions + demos)     │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│                    ONLINE (extraction pipeline)                   │
│                                                                  │
│  PDF/MD → extract_red_flags() → [candidate flags]                │
│                                       │                          │
│                                       ▼                          │
│                              verify_red_flags()                  │
│                              (loads verifier_prompt.json,        │
│                               single OpenAI call per document,   │
│                               returns items where flag=True)     │
│                                       │                          │
│                                       ▼                          │
│                            validate_and_build_entries()           │
│                            (+ URL-based regulator override)      │
│                                       │                          │
│                                       ▼                          │
│                              write_yaml() → data/source/         │
└──────────────────────────────────────────────────────────────────┘
```

## Implementation Units

- [ ] **Unit 1: Extract prompts into `scripts/prompts.py`**

**Goal:** Move the extraction prompt out of `extract.py` into a dedicated module, establishing the pattern for adding the verification prompt.

**Requirements:** R7

**Dependencies:** None

**Files:**
- Create: `scripts/prompts.py`
- Modify: `scripts/extract.py`
- Modify: `tests/test_extract.py`

**Approach:**
- Move `build_extraction_prompt()` and its entire system prompt string from `extract.py` to `prompts.py`
- `extract.py` imports `build_extraction_prompt` from `prompts`
- All existing tests in `test_extract.py` that test the prompt content should continue passing with the import redirect
- No behavioral changes — pure refactor

**Patterns to follow:**
- Existing import pattern in `extract.py` (e.g., `from redflag_mcp.config import ...`)

**Test scenarios:**
- All existing `TestBuildExtractionPrompt` tests pass unchanged
- `build_extraction_prompt` is importable from both `prompts` and `extract` (re-export)

**Verification:**
- `uv run pytest tests/test_extract.py` passes with no changes to test assertions

---

- [ ] **Unit 2: Add URL-based regulator inference**

**Goal:** Infer the regulator from the source URL domain, using LLM-extracted value only as fallback.

**Requirements:** R8

**Dependencies:** None (can be done in parallel with Unit 1)

**Files:**
- Modify: `src/redflag_mcp/config.py`
- Modify: `scripts/extract.py`
- Modify: `tests/test_extract.py`

**Approach:**
- Add `URL_DOMAIN_TO_REGULATOR` dict to `config.py` mapping ~25 domains to regulator strings (using the audit above)
- Add `regulator_from_url(url: str) -> str | None` function to `config.py` that parses the domain and looks it up
- In `validate_and_build_entries()`, when `source_url` is available, call `regulator_from_url(source_url)` and use that as the primary regulator, falling back to the LLM-extracted value
- Add new regulators to `REGULATORS` and `REGULATOR_JURISDICTIONS` sets/dicts as needed (NCA, OFSI, CBUAE, SAMA, RBI)

**Patterns to follow:**
- Existing `jurisdiction_for_regulator()` in `config.py`
- Existing `validate_and_build_entries()` logic that derives jurisdiction from regulator

**Test scenarios:**
- `regulator_from_url("https://ofac.treasury.gov/media/123/download")` returns `"OFAC"`
- `regulator_from_url("https://www.fincen.gov/system/files/alert.pdf")` returns `"FinCEN"`
- `regulator_from_url("https://unknown-domain.com/doc.pdf")` returns `None`
- `validate_and_build_entries` with `source_url` from OFAC domain overrides LLM-extracted `"FBI"` to `"OFAC"`
- Fallback: when URL domain is unmapped, LLM-extracted regulator is preserved

**Verification:**
- `uv run pytest tests/test_extract.py` passes including new regulator inference tests
- Existing regulator jurisdiction tests still pass

---

- [ ] **Unit 3: Add verification prompt and `verify_red_flags()` function**

**Goal:** Create the verifier that filters candidate red flags using a second LLM call.

**Requirements:** R1, R2, R5, R6

**Dependencies:** Unit 1 (prompts module exists)

**Files:**
- Modify: `scripts/prompts.py`
- Modify: `scripts/extract.py`
- Modify: `tests/test_extract.py`

**Approach:**
- Add `build_verification_prompt(descriptions: list[str]) -> list[dict]` to `prompts.py`. The prompt takes a list of description strings and asks the LLM to classify each as True/False, returning JSON like `{"results": [{"index": 0, "flag": true}, ...]}`.
- Add `verify_red_flags(candidates: list[dict], model: str | None = None) -> list[dict]` to `extract.py`. This function:
  - Extracts descriptions from candidates
  - Calls OpenAI with the verification prompt (single call per document, satisfying R6)
  - Filters candidates to only those classified as True
  - Returns the filtered list
- Integrate into `process_one()` between `extract_red_flags()` and `validate_and_build_entries()`
- Add `--no-verify` CLI flag that skips the verification step
- The verification prompt should focus on the core classification question: "Is this description an observable suspicious behavior (customer, transaction, account, entity) that a compliance officer could detect? Or is it compliance guidance, regulatory instruction, case narrative, or general background?"

**Patterns to follow:**
- Existing `extract_red_flags()` pattern for OpenAI API calls
- Existing CLI flag parsing in `main()` (e.g., `--force`, `--parallel`)

**Test scenarios:**
- `verify_red_flags()` with a mix of real red flags and compliance guidance returns only the red flags (mock OpenAI)
- `verify_red_flags()` with empty list returns empty list
- `process_one()` with `--no-verify` skips verification step
- `process_one()` default behavior includes verification
- Verification prompt contains key classification criteria

**Verification:**
- `uv run pytest tests/test_extract.py` passes
- Manual test: `uv run python scripts/extract.py --force --no-verify red_flag_sources/pdf/048*.pdf` produces all 45 items (no filtering), while without `--no-verify` it produces 0 or near-0 items

---

- [ ] **Unit 4: Build eval script**

**Goal:** Create `scripts/eval_verifier.py` that measures verifier accuracy against labelled data.

**Requirements:** R3

**Dependencies:** Unit 3 (verify_red_flags exists)

**Files:**
- Create: `scripts/eval_verifier.py`
- Create: `tests/test_eval_verifier.py`

**Approach:**
- Load all `data/source/labelled/*.yaml` files
- For each item, run the verifier on the description and compare predicted flag to labelled flag
- Report: precision, recall, F1, accuracy, confusion matrix (TP/FP/TN/FN counts)
- Also report baseline metrics (no verifier — all items classified as True) for comparison
- Support `--model` flag to test different models
- Output both human-readable table and optional JSON (`--json` flag) for programmatic consumption

**Patterns to follow:**
- Existing script patterns in `scripts/` (argparse-style CLI, dotenv loading)
- Labelled data format with `flag: True/False` field

**Test scenarios:**
- Eval script correctly computes metrics for a known set of predictions
- Baseline computation is correct (all-True predictions)
- Script handles missing `flag` field gracefully (skips items)

**Verification:**
- `uv run python scripts/eval_verifier.py` runs and produces a metrics table
- Metrics are plausible against the known distribution (35 True, 53 False)

---

- [ ] **Unit 5: DSPy optimization script**

**Goal:** Create `scripts/optimize_verifier.py` that uses DSPy to find the best verifier prompt.

**Requirements:** R4

**Dependencies:** Unit 4 (eval infrastructure exists)

**Files:**
- Create: `scripts/optimize_verifier.py`
- Modify: `pyproject.toml` (add `dspy` dependency)

**Approach:**
- Add `dspy>=2.6` to `pyproject.toml` dependencies
- Define a DSPy `Signature` for red flag classification: `description -> is_red_flag: bool` with descriptive field annotations
- Define a DSPy module using `dspy.ChainOfThought` (reasoning before classification) or `dspy.Predict` — try both
- Load labelled data as `dspy.Example` instances with `description` as input and `is_red_flag` as the label
- Split into train/test (70/30 or leave-one-document-out cross-validation)
- Use `BootstrapFewShot` optimizer with a metric that weights precision heavily (e.g., `precision * 0.7 + recall * 0.3` or F-beta with beta=0.5)
- Configure `dspy.LM("openai/gpt-5.4-nano")`
- Save optimized program to `data/verifier_prompt.json`
- The production verifier in `extract.py` can then load the optimized instructions and demo examples from this JSON and build its OpenAI prompt accordingly

**Patterns to follow:**
- DSPy 2.x patterns: `dspy.configure(lm=...)`, `BootstrapFewShot(metric=..., max_bootstrapped_demos=4, max_labeled_demos=4)`, `program.save("path.json")`

**Test scenarios:**
- Script can load labelled data and create DSPy examples
- DSPy signature produces bool output
- Optimized program saves to JSON and can be loaded back
- Integration: optimized prompt achieves <10% false positive rate on test split

**Verification:**
- `uv run python scripts/optimize_verifier.py` completes and saves `data/verifier_prompt.json`
- `uv run python scripts/eval_verifier.py` shows improved metrics after loading optimized prompt

---

- [ ] **Unit 6: Integrate optimized prompt into production verifier**

**Goal:** Update `verify_red_flags()` to load and use the DSPy-optimized prompt when available.

**Requirements:** R1, R4 (integration)

**Dependencies:** Unit 5 (optimized prompt exists)

**Files:**
- Modify: `scripts/prompts.py`
- Modify: `scripts/extract.py`
- Modify: `tests/test_extract.py`

**Approach:**
- `build_verification_prompt()` checks for `data/verifier_prompt.json`. If it exists, loads the optimized instructions and few-shot demos and builds the prompt from them. Otherwise falls back to the handcrafted prompt from Unit 3.
- This keeps the system functional before optimization runs (handcrafted prompt) and improves after optimization (DSPy-optimized prompt)
- Log which prompt source is being used (handcrafted vs optimized)

**Patterns to follow:**
- Existing `load_manifest()` pattern for optional JSON file loading

**Test scenarios:**
- With `verifier_prompt.json` present, verification uses optimized prompt
- Without `verifier_prompt.json`, verification uses handcrafted fallback
- Optimized prompt produces correct JSON structure for the verifier

**Verification:**
- `uv run python scripts/eval_verifier.py` confirms <10% false positive rate with optimized prompt
- `uv run pytest tests/test_extract.py` passes

## System-Wide Impact

- **Interaction graph:** The verifier adds one additional OpenAI API call per document extraction. No impact on the MCP server, ingestion, or query paths.
- **Error propagation:** If the verifier call fails, `process_one()` should log a warning and proceed with unverified candidates rather than failing the entire extraction. This matches the existing pattern for `update_registry_after_extraction()`.
- **State lifecycle:** The optimized prompt file (`data/verifier_prompt.json`) is a durable artifact. It should be committed to git so that the pipeline works without re-running optimization.
- **API surface parity:** No changes to MCP tools or server behavior. This is entirely in the extraction pipeline.

## Risks & Dependencies

- **DSPy API stability**: DSPy 2.x is relatively new. Pin to a specific version range to avoid breaking changes.
- **Labelled dataset size**: 90 examples across 5 documents is small. The verifier may overfit to these document types. Mitigation: use leave-one-document-out cross-validation during optimization.
- **OpenAI cost**: Running DSPy optimization involves many LLM calls. Using `gpt-5.4-nano` keeps costs manageable. The optimization is a one-time cost.
- **New regulators**: Adding NCA, OFSI, CBUAE, SAMA, RBI to the regulators set may affect downstream validation if `RedFlagSource` model has strict enum validation — verify the model accepts these values.

## Sources & References

- **Origin document:** [docs/brainstorms/2026-05-24-red-flag-verifier-requirements.md](docs/brainstorms/2026-05-24-red-flag-verifier-requirements.md)
- Related code: `scripts/extract.py`, `src/redflag_mcp/config.py`, `tests/test_extract.py`
- DSPy docs: https://dspy.ai/learn/optimization/optimizers/, https://dspy.ai/learn/programming/signatures/
- DSPy binary classification: https://dspy.ai/cheatsheet/
- DSPy save/load: https://dspy.ai/tutorials/saving/
