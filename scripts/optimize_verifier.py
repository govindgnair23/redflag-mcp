#!/usr/bin/env python3
"""Optimize the red-flag verifier prompt using DSPy.

Usage:
    uv run --extra optimize python scripts/optimize_verifier.py
    uv run --extra optimize python scripts/optimize_verifier.py --model openai/gpt-4o-mini
    uv run --extra optimize python scripts/optimize_verifier.py --max-demos 4
    uv run --extra optimize python scripts/optimize_verifier.py --strategy predict  # or cot
    uv run --extra optimize python scripts/optimize_verifier.py --optimizer mipro
    uv run --extra optimize python scripts/optimize_verifier.py --optimizer mipro --auto light

Optimizer options:
    bootstrap  (default) BootstrapFewShotWithRandomSearch — fast, demos only
    mipro      MIPROv2 — optimizes both instructions and demos jointly (more LLM calls)

For mipro, --auto controls intensity: light / medium (default) / heavy

Loads labelled data from data/source/labelled/, trains a DSPy program,
and saves the optimized prompt to data/verifier_prompt.json.

Requires OPENAI_API_KEY and the 'optimize' extra: uv sync --extra optimize
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

try:
    import dspy
except ImportError:
    print(
        "Error: dspy is not installed. Run: uv sync --extra optimize",
        file=sys.stderr,
    )
    sys.exit(1)

LABELLED_DIR = Path(__file__).resolve().parent.parent / "data" / "source" / "labelled"
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "verifier_prompt.json"

DEFAULT_MODEL = "openai/gpt-5.4-nano"
DEFAULT_MAX_DEMOS = 4
DEFAULT_STRATEGY = "cot"  # "predict" or "cot"
DEFAULT_OPTIMIZER = "bootstrap"  # "bootstrap" or "mipro"
DEFAULT_AUTO = "medium"  # mipro intensity: "light", "medium", or "heavy"


class RedFlagClassifier(dspy.Signature):
    """Classify whether a candidate description extracted from a regulatory
    document is a genuine AML red flag (observable suspicious behavior) or
    not (compliance guidance, regulatory instruction, case narrative, etc.)."""

    description: str = dspy.InputField(
        desc="A candidate red flag description extracted from a regulatory document."
    )
    is_red_flag: bool = dspy.OutputField(
        desc="True if the description is an observable suspicious behavior "
        "that a compliance officer could detect; False if it is compliance "
        "guidance, regulatory instruction, case narrative, or background."
    )


class RedFlagPredict(dspy.Module):
    def __init__(self):
        self.classify = dspy.Predict(RedFlagClassifier)

    def forward(self, description: str) -> dspy.Prediction:
        return self.classify(description=description)


class RedFlagCoT(dspy.Module):
    def __init__(self):
        self.classify = dspy.ChainOfThought(RedFlagClassifier)

    def forward(self, description: str) -> dspy.Prediction:
        return self.classify(description=description)


def load_labelled_examples() -> list[dspy.Example]:
    """Load labelled YAML files and convert to DSPy Examples.

    When a 'reasoning' field is present, it is included as a labeled
    demonstration so DSPy uses the human-written reasoning rather than
    bootstrapping its own. This is particularly useful for False examples
    where the distinction from a genuine red flag is subtle.
    """
    examples = []
    with_reasoning = 0
    for path in sorted(LABELLED_DIR.glob("*.yaml")):
        with open(path) as f:
            docs = yaml.safe_load(f)
        if not isinstance(docs, list):
            continue
        for item in docs:
            if "flag" not in item or "description" not in item:
                continue
            kwargs: dict = {
                "description": item["description"],
                "is_red_flag": bool(item["flag"]),
            }
            if item.get("reasoning"):
                kwargs["reasoning"] = item["reasoning"]
                with_reasoning += 1
            ex = dspy.Example(**kwargs).with_inputs("description")
            examples.append(ex)
    print(f"  {len(examples)} examples loaded ({with_reasoning} with human reasoning).")
    return examples


def precision_weighted_metric(example, prediction, trace=None) -> float:
    """Metric that weights precision heavily over recall.

    Returns 1.0 for correct predictions, 0.0 for incorrect.
    When used with BootstrapFewShot, the optimizer maximizes overall
    accuracy but the demo selection naturally favors precision.
    """
    pred_val = prediction.is_red_flag
    if isinstance(pred_val, str):
        pred_val = pred_val.lower() in ("true", "yes", "1")

    label = bool(example.is_red_flag)
    predicted = bool(pred_val)

    if label == predicted:
        return 1.0

    # Penalize false positives (predicting True when label is False) more heavily
    if predicted and not label:
        return -0.5  # false positive penalty

    # False negative (predicting False when label is True) — moderate penalty
    return 0.0


def run_optimization(
    model: str = DEFAULT_MODEL,
    max_demos: int = DEFAULT_MAX_DEMOS,
    strategy: str = DEFAULT_STRATEGY,
    optimizer: str = DEFAULT_OPTIMIZER,
    auto: str = DEFAULT_AUTO,
    seed: int = 42,
) -> None:
    """Run DSPy optimization and save the optimized program."""
    random.seed(seed)

    print(f"Configuring DSPy with model: {model}")
    lm = dspy.LM(model)
    dspy.configure(lm=lm)

    examples = load_labelled_examples()
    print(f"Loaded {len(examples)} labelled examples.")

    if len(examples) < 10:
        print("Error: Too few labelled examples for optimization.", file=sys.stderr)
        sys.exit(1)

    # Split: 70% train, 30% test
    random.shuffle(examples)
    split_idx = int(len(examples) * 0.7)
    train_set = examples[:split_idx]
    test_set = examples[split_idx:]

    true_train = sum(1 for e in train_set if e.is_red_flag)
    false_train = len(train_set) - true_train
    true_test = sum(1 for e in test_set if e.is_red_flag)
    false_test = len(test_set) - true_test

    print(f"Train: {len(train_set)} ({true_train} true, {false_train} false)")
    print(f"Test:  {len(test_set)} ({true_test} true, {false_test} false)")

    # Create the module
    if strategy == "predict":
        print("Using Predict strategy (direct classification).")
        program = RedFlagPredict()
    else:
        print("Using ChainOfThought strategy (reasoning before classification).")
        program = RedFlagCoT()

    # Optimize
    if optimizer == "mipro":
        print(f"Running MIPROv2 (auto={auto}) — optimizes instructions + demos jointly.")
        print("  This makes significantly more LLM calls than bootstrap.")
        opt = dspy.MIPROv2(
            metric=precision_weighted_metric,
            auto=auto,
            num_threads=4,
        )
        optimized = opt.compile(
            program,
            trainset=train_set,
            requires_permission_to_run=False,
        )
    else:
        print(f"Running BootstrapFewShotWithRandomSearch (max_demos={max_demos})...")
        opt = dspy.BootstrapFewShotWithRandomSearch(
            metric=precision_weighted_metric,
            max_bootstrapped_demos=max_demos,
            max_labeled_demos=max_demos,
            num_candidate_programs=8,
            num_threads=4,
        )
        optimized = opt.compile(program, trainset=train_set)

    # Evaluate on test set
    print("\nEvaluating on test set...")
    tp = fp = tn = fn = 0
    for ex in test_set:
        pred = optimized(description=ex.description)
        pred_val = pred.is_red_flag
        if isinstance(pred_val, str):
            pred_val = pred_val.lower() in ("true", "yes", "1")
        pred_val = bool(pred_val)
        label = bool(ex.is_red_flag)

        if label and pred_val:
            tp += 1
        elif not label and pred_val:
            fp += 1
        elif not label and not pred_val:
            tn += 1
        else:
            fn += 1

    total = len(test_set)
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    accuracy = (tp + tn) / total if total > 0 else 0.0

    print(f"\nTest Results:")
    print(f"  Precision: {precision:.4f}")
    print(f"  Recall:    {recall:.4f}")
    print(f"  F1:        {f1:.4f}")
    print(f"  Accuracy:  {accuracy:.4f}")
    print(f"  TP={tp}  FP={fp}")
    print(f"  FN={fn}  TN={tn}")

    fp_rate = fp / (fp + tn) if (fp + tn) > 0 else 0.0
    print(f"  False Positive Rate: {fp_rate:.4f}")

    # Save the optimized program
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    optimized.save(str(OUTPUT_PATH))
    print(f"\nOptimized program saved to {OUTPUT_PATH}")


def main() -> None:
    args = sys.argv[1:]

    model = DEFAULT_MODEL
    if "--model" in args:
        idx = args.index("--model")
        args.pop(idx)
        if idx < len(args):
            model = args.pop(idx)

    max_demos = DEFAULT_MAX_DEMOS
    if "--max-demos" in args:
        idx = args.index("--max-demos")
        args.pop(idx)
        if idx < len(args):
            max_demos = int(args.pop(idx))

    strategy = DEFAULT_STRATEGY
    if "--strategy" in args:
        idx = args.index("--strategy")
        args.pop(idx)
        if idx < len(args):
            strategy = args.pop(idx)

    optimizer = DEFAULT_OPTIMIZER
    if "--optimizer" in args:
        idx = args.index("--optimizer")
        args.pop(idx)
        if idx < len(args):
            optimizer = args.pop(idx)
            if optimizer not in ("bootstrap", "mipro"):
                print("Error: --optimizer must be 'bootstrap' or 'mipro'.", file=sys.stderr)
                sys.exit(1)

    auto = DEFAULT_AUTO
    if "--auto" in args:
        idx = args.index("--auto")
        args.pop(idx)
        if idx < len(args):
            auto = args.pop(idx)
            if auto not in ("light", "medium", "heavy"):
                print("Error: --auto must be 'light', 'medium', or 'heavy'.", file=sys.stderr)
                sys.exit(1)

    seed = 42
    if "--seed" in args:
        idx = args.index("--seed")
        args.pop(idx)
        if idx < len(args):
            seed = int(args.pop(idx))

    run_optimization(
        model=model,
        max_demos=max_demos,
        strategy=strategy,
        optimizer=optimizer,
        auto=auto,
        seed=seed,
    )


if __name__ == "__main__":
    main()
