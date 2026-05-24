#!/usr/bin/env python3
"""Evaluate the red-flag verifier against labelled data.

Usage:
    uv run python scripts/eval_verifier.py
    uv run python scripts/eval_verifier.py --model gpt-4o
    uv run python scripts/eval_verifier.py --json

Loads labelled YAML files from data/source/labelled/, runs the verifier
on each description, and reports precision, recall, F1, and accuracy.
Also reports baseline metrics (no verifier — all items classified as True).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

# Add scripts and src to path
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from extract import verify_red_flags  # noqa: E402

LABELLED_DIR = Path(__file__).resolve().parent.parent / "data" / "source" / "labelled"


def load_labelled_data() -> list[dict]:
    """Load all labelled YAML files and return items with flag field."""
    items = []
    for path in sorted(LABELLED_DIR.glob("*.yaml")):
        with open(path) as f:
            docs = yaml.safe_load(f)
        if not isinstance(docs, list):
            continue
        for item in docs:
            if "flag" not in item:
                continue
            item["_source_file"] = path.name
            items.append(item)
    return items


def compute_metrics(
    labels: list[bool], predictions: list[bool]
) -> dict:
    """Compute precision, recall, F1, accuracy from parallel label/prediction lists."""
    tp = sum(1 for l, p in zip(labels, predictions) if l and p)
    fp = sum(1 for l, p in zip(labels, predictions) if not l and p)
    tn = sum(1 for l, p in zip(labels, predictions) if not l and not p)
    fn = sum(1 for l, p in zip(labels, predictions) if l and not p)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    accuracy = (tp + tn) / len(labels) if labels else 0.0

    return {
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "accuracy": round(accuracy, 4),
        "total": len(labels),
    }


def run_eval(model: str | None = None, force_handcrafted: bool = False) -> dict:
    """Run the verifier against labelled data and return metrics."""
    items = load_labelled_data()
    if not items:
        print("Error: No labelled data found.", file=sys.stderr)
        sys.exit(1)

    labels = [bool(item["flag"]) for item in items]

    # Baseline: all items classified as True (no verifier)
    baseline_preds = [True] * len(labels)
    baseline_metrics = compute_metrics(labels, baseline_preds)

    # Verifier predictions: run verify_red_flags and check which items survive
    verified = verify_red_flags(items, model=model, force_handcrafted=force_handcrafted)
    verified_descs = {item["description"] for item in verified}
    verifier_preds = [item["description"] in verified_descs for item in items]
    verifier_metrics = compute_metrics(labels, verifier_preds)

    prompt_label = "handcrafted" if force_handcrafted else "optimized (if available)"
    return {
        "baseline": baseline_metrics,
        "verifier": verifier_metrics,
        "model": model or "default",
        "prompt": prompt_label,
        "labelled_count": len(items),
        "true_count": sum(labels),
        "false_count": sum(not l for l in labels),
    }


def print_metrics_table(results: dict) -> None:
    """Print a human-readable metrics table."""
    print(f"\nEval Results ({results['labelled_count']} items: "
          f"{results['true_count']} true, {results['false_count']} false)")
    print(f"Model:  {results['model']}")
    print(f"Prompt: {results['prompt']}")
    print("-" * 60)
    print(f"{'Metric':<12} {'Baseline':>10} {'Verifier':>10}")
    print("-" * 60)

    b = results["baseline"]
    v = results["verifier"]

    for metric in ["precision", "recall", "f1", "accuracy"]:
        print(f"{metric:<12} {b[metric]:>10.4f} {v[metric]:>10.4f}")

    print("-" * 60)
    print(f"\nConfusion Matrix (Verifier):")
    print(f"  TP={v['tp']}  FP={v['fp']}")
    print(f"  FN={v['fn']}  TN={v['tn']}")

    print(f"\nConfusion Matrix (Baseline):")
    print(f"  TP={b['tp']}  FP={b['fp']}")
    print(f"  FN={b['fn']}  TN={b['tn']}")


def main() -> None:
    args = sys.argv[1:]

    model: str | None = None
    if "--model" in args:
        idx = args.index("--model")
        args.pop(idx)
        if idx < len(args):
            model = args.pop(idx)
        else:
            print("Error: --model requires a value.", file=sys.stderr)
            sys.exit(1)

    force_handcrafted = False
    if "--prompt" in args:
        idx = args.index("--prompt")
        args.pop(idx)
        if idx < len(args):
            prompt_choice = args.pop(idx)
            if prompt_choice == "handcrafted":
                force_handcrafted = True
            elif prompt_choice != "optimized":
                print("Error: --prompt must be 'handcrafted' or 'optimized'.", file=sys.stderr)
                sys.exit(1)

    output_json = "--json" in args
    if output_json:
        args.remove("--json")

    results = run_eval(model=model, force_handcrafted=force_handcrafted)

    if output_json:
        print(json.dumps(results, indent=2))
    else:
        print_metrics_table(results)


if __name__ == "__main__":
    main()
