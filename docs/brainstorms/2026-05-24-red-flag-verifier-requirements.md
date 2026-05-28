---
date: 2026-05-24
topic: red-flag-verifier
---

# Red Flag Extraction Verifier

## Problem Frame

The extraction prompt in `scripts/extract.py` produces a 59% false positive rate. Despite detailed instructions to exclude compliance guidance, regulatory directives, case narratives, and institutional obligations, the LLM still extracts them as red flags. Document 048 (OFAC compliance framework) alone contributed 45 false positives with zero valid red flags. The existing prompt has reached diminishing returns on instruction complexity — a second-stage verification step is needed to filter out non-red-flags before they enter the data pipeline.

## Requirements

- R1. **Verifier step in extraction pipeline.** After the extraction LLM call returns candidate red flags, a second LLM call classifies each item as `flag: True` (genuine red flag) or `flag: False` (not a red flag). Only items classified `True` proceed to validation and YAML output.
- R2. **Description-only input.** The verifier receives only the extracted item's `description` text — not the source document. This keeps cost low and makes the verifier a standalone binary classifier.
- R3. **Eval script against labelled dataset.** A script (`scripts/eval_verifier.py` or similar) runs the verifier against `data/source/labelled/*.yaml` and reports precision, recall, F1, and a confusion matrix. This is the feedback loop for prompt iteration.
- R4. **DSPy prompt optimization.** Use DSPy to automatically optimize the verifier prompt against the labelled dataset, maximizing precision while maintaining acceptable recall.
- R5. **Integration with existing pipeline.** The verifier step integrates into `extract.py`'s `process_one()` flow. It should be optional via a `--no-verify` flag for backward compatibility or debugging. Verification is on by default.
- R6. **Batch verification.** The verifier should classify items in a single batched LLM call (or small number of calls) rather than one call per item, to minimize latency and cost.
- R7. **Prompts in separate file.** Move the extraction prompt and the new verification prompt out of `extract.py` into a dedicated prompts module (e.g., `scripts/prompts.py` or `src/redflag_mcp/prompts.py`). Keeps `extract.py` focused on pipeline orchestration.
- R8. **Regulator inference from source URL.** The regulator field should be primarily inferred from the source URL domain (e.g., `ofac.treasury.gov` → OFAC, `fincen.gov` → FinCEN), not from LLM extraction. The LLM-extracted regulator is used only as a fallback when no URL is available or the domain is not in the mapping. This fixes misattribution like document 051 being tagged as FBI when the source is an OFAC website.

## Success Criteria

- False positive rate on the labelled dataset drops below 10% (from current 59%)
- Recall of true red flags remains above 90%
- No new dependencies beyond DSPy (and its transitive deps)
- Extraction pipeline wall-clock time increases by no more than 2x

## Scope Boundaries

- **Not changing the extraction prompt.** The first-stage prompt stays as-is. Improvements come from the verifier.
- **No LangGraph or multi-agent framework.** Simple sequential LLM call in Python.
- **No fine-tuning.** The verifier uses prompted classification, not a fine-tuned model.
- **No UI or human-in-the-loop.** Fully automated pipeline.

## Key Decisions

- **Description-only verification:** Keeps the verifier cheap, fast, and independently testable. The verifier doesn't need source context because the classification task ("is this description an observable suspicious behavior?") is self-contained.
- **DSPy over manual prompt tuning:** The labelled dataset (90 items, 35 true, 53 false across 5 documents) is small but sufficient for DSPy's few-shot optimization. DSPy can automatically select the best examples and prompt structure.
- **Batch classification:** Sending all items from one document in a single verifier call reduces API round-trips and lets the model see the full set for deduplication context.
- **URL-based regulator inference:** Domain-to-regulator mapping is deterministic and more reliable than LLM extraction. The LLM often picks the wrong agency when a document is jointly issued or hosted on one agency's site but references another.
- **Prompts as a separate module:** The extraction prompt is already ~230 lines. Adding a verification prompt would make `extract.py` even harder to navigate. Separating prompts improves readability and makes prompt iteration (manual or via DSPy) easier.

## Dependencies / Assumptions

- DSPy is compatible with OpenAI API (gpt-4o-mini) — confirmed, DSPy supports OpenAI as a backend
- The labelled dataset is representative enough to generalize. 5 documents covering compliance frameworks, sanctions advisories, and cyber threat advisories provide reasonable diversity.
- The labelled dataset will grow over time as more documents are curated

## Outstanding Questions

### Deferred to Planning

- [Affects R4][Needs research] What DSPy module/optimizer is best suited for binary classification with ~90 labelled examples? (e.g., `BootstrapFewShot`, `MIPROv2`)
- [Affects R6][Technical] Should the batch verifier use structured output (JSON mode) or free-text with parsing? Need to check DSPy's support for structured outputs with OpenAI.
- [Affects R3][Technical] Should the eval script also measure performance of the extraction prompt alone (before verifier) as a baseline comparison?
- [Affects R8][Technical] What is the full domain-to-regulator mapping needed? Audit existing source URLs to build the lookup table.

## Next Steps

→ `/ce:plan` for structured implementation planning
