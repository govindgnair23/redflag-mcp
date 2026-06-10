#!/usr/bin/env python3
"""Clean red flag YAML files: deduplicate records, expand abbreviations, fix broken descriptions.

Usage:
    # Single file
    uv run python scripts/clean.py data/source/123.yaml

    # Multiple files
    uv run python scripts/clean.py data/source/122.yaml data/source/123.yaml

    # Preview changes without writing
    uv run python scripts/clean.py --dry-run data/source/123.yaml

    # Override model
    uv run python scripts/clean.py --model gpt-4o data/source/123.yaml

Edits each YAML file in-place. Use --dry-run to print planned changes without
writing. Records removed as duplicates are listed with the ID they duplicate.

Requires OPENAI_API_KEY environment variable (or .env file).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from prompts import build_clean_prompt  # noqa: E402

DEFAULT_MODEL = "gpt-5.4-mini"
LOGGER = logging.getLogger(__name__)


def clean_file(path: Path, dry_run: bool = False, model: str = DEFAULT_MODEL) -> None:
    """Clean a single YAML source file in-place."""
    with open(path) as f:
        records: list[dict] = yaml.safe_load(f) or []

    if not records:
        print(f"{path.name}: empty, skipping")
        return

    print(f"{path.name}: {len(records)} records — sending to {model}...")

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("Error: OPENAI_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    client = OpenAI(api_key=api_key)
    messages = build_clean_prompt(records)

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        response_format={"type": "json_object"},
        temperature=0.0,
    )

    raw = response.choices[0].message.content
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"  Error: LLM returned invalid JSON: {exc}", file=sys.stderr)
        print(f"  Raw response: {raw[:500]}", file=sys.stderr)
        return

    result_by_id: dict[str, dict] = {r["id"]: r for r in result.get("records", [])}

    # Warn about any IDs the model dropped entirely.
    input_ids = {rec["id"] for rec in records}
    missing = input_ids - result_by_id.keys()
    if missing:
        print(f"  Warning: model did not return results for {missing} — keeping as-is")

    kept: list[dict] = []
    removed: list[tuple[str, str]] = []
    updated: list[tuple[str, str, str]] = []

    for record in records:
        rid = record["id"]
        res = result_by_id.get(rid)

        if res is None:
            kept.append(record)
            continue

        if not res.get("keep", True):
            removed.append((rid, res.get("duplicate_of", "?")))
            continue

        new_desc = res.get("description", record.get("description", ""))
        if new_desc != record.get("description", ""):
            updated.append((rid, record.get("description", ""), new_desc))
            record = {**record, "description": new_desc}

        kept.append(record)

    # Report description changes.
    if updated:
        print(f"  Descriptions updated ({len(updated)}):")
        for rid, old, new in updated:
            old_preview = old[:70].replace("\n", " ")
            new_preview = new[:70].replace("\n", " ")
            print(f"    {rid}")
            print(f"      before: {old_preview!r}")
            print(f"      after:  {new_preview!r}")

    # Report removals.
    if removed:
        print(f"  Duplicates removed ({len(removed)}):")
        for rid, dup_of in removed:
            print(f"    {rid}  (duplicate of {dup_of})")

    if not updated and not removed:
        print(f"  {path.name}: no changes needed")
        return

    print(f"  {path.name}: {len(records)} → {len(kept)} records")

    if dry_run:
        print("  (dry run — not writing)")
        return

    with open(path, "w") as f:
        yaml.dump(
            kept,
            f,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
            width=88,
        )
    print(f"  Saved: {path}")


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(message)s")

    parser = argparse.ArgumentParser(
        description=(
            "Clean red flag YAML files: deduplicate records, expand abbreviations, "
            "fix broken descriptions."
        )
    )
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        metavar="YAML_PATH",
        help="One or more data/source/*.yaml files to clean.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show planned changes without writing to disk.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"OpenAI model to use (default: {DEFAULT_MODEL}).",
    )
    args = parser.parse_args()

    for path in args.paths:
        if not path.exists():
            print(f"Error: {path} does not exist", file=sys.stderr)
            continue
        clean_file(path, dry_run=args.dry_run, model=args.model)


if __name__ == "__main__":
    main()
