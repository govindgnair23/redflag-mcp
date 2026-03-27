#!/usr/bin/env python3
"""Extract AML red flags from PDFs or web pages using an LLM.

Usage:
    uv run python scripts/extract.py <pdf-path-or-url>
    uv run python scripts/extract.py --force <pdf-path-or-url>

Outputs a YAML file in data/source/ conforming to the RedFlagSource schema.
Tracks processed sources in data/source/.extracted_sources.yaml to avoid
re-processing. Use --force to bypass the duplicate check.
Requires OPENAI_API_KEY environment variable.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pdfplumber
import yaml
from bs4 import BeautifulSoup
from openai import OpenAI
from pydantic import ValidationError

# Add src to path so we can import redflag_mcp
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from redflag_mcp.config import RISK_LEVELS, SIMULATION_TYPES, SOURCE_DIR
from redflag_mcp.models import RedFlagSource

DEFAULT_MODEL = "gpt-4o-mini"
MANIFEST_PATH = SOURCE_DIR / ".extracted_sources.yaml"


def load_manifest() -> list[dict]:
    """Load the extraction manifest, or return an empty list if it doesn't exist."""
    if not MANIFEST_PATH.exists():
        return []
    with open(MANIFEST_PATH) as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, list) else []


def save_manifest(manifest: list[dict]) -> None:
    """Write the extraction manifest to disk."""
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST_PATH, "w") as f:
        yaml.dump(manifest, f, default_flow_style=False, sort_keys=False)


def is_already_processed(source: str, manifest: list[dict]) -> bool:
    """Check if a source has already been processed."""
    return any(entry.get("source") == source for entry in manifest)


def slugify(text: str) -> str:
    """Convert text to a URL-friendly slug."""
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[-\s]+", "-", text).strip("-")
    return text


def extract_text_from_pdf(pdf_path: str) -> str:
    """Extract all text from a PDF file using pdfplumber."""
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
    return "\n\n".join(pages)


def extract_text_from_url(url: str) -> str:
    """Fetch a web page and extract its text content."""
    response = httpx.get(
        url,
        timeout=30.0,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        },
        follow_redirects=True,
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    # Remove non-content elements
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()

    return soup.get_text(separator="\n", strip=True)


def source_slug(source: str) -> str:
    """Generate a slug from a PDF filename or URL."""
    if source.startswith(("http://", "https://")):
        from urllib.parse import urlparse

        parsed = urlparse(source)
        # Combine domain and path for a meaningful slug
        parts = [parsed.netloc.split(".")[0]]  # first part of domain
        path = parsed.path.strip("/")
        if path:
            # Use the last 2-3 meaningful path segments
            segments = [s for s in path.split("/") if s]
            parts.extend(segments[-3:])
        return slugify("-".join(parts))
    else:
        # Use the PDF filename without extension
        filename = Path(source).stem
        return slugify(filename)


def build_extraction_prompt(document_text: str) -> list[dict]:
    """Build the system and user prompts for LLM extraction."""
    system_prompt = f"""You are an AML compliance expert. Extract all distinct AML red flags from the provided regulatory document using a two-step process.

## Step 1 — Identify red flags

Read the document carefully and list every distinct behavioral or transactional indicator that signals potential money laundering or financial crime. Be thorough: red flags are often embedded in prose paragraphs, not just bullet lists. Do not summarize sections — each entry must be a single, standalone indicator.

## Step 2 — Analyze each red flag

For each indicator identified in Step 1, determine the following metadata:

- "description" (string, required): Copy the indicator text exactly as it appears in the source document. Do not paraphrase, generalize, or remove any wording.
- "product_types" (list of strings): Which financial products or channels does this indicator apply to? Choose from: "depository", "credit_card", "money_transmitter", "prepaid", "securities", "insurance", "crypto", "msb", "private_banking", "correspondent_banking", "trade_finance". Include all that apply.
- "regulatory_source" (string): The full name of the issuing document or authority (e.g., "FinCEN Alert FIN-2022-Alert001", "FFIEC BSA/AML Examination Manual Appendix F").
- "risk_level" (string): Severity of the indicator. One of: {sorted(RISK_LEVELS)}. Use "high" for indicators directly tied to confirmed typologies or sanctions violations; "medium" for suspicious patterns requiring investigation; "low" for weak signals that need corroboration.
- "category" (string): The primary AML typology. Use: "structuring", "layering", "sanctions_evasion", "terrorist_financing", "fraud_nexus", "corruption", "shell_company", "trade_based_ml", "cyber_enabled", "ransomware", "virtual_currency". If multiple apply, choose the most specific.
- "simulation_type" (string or null): Classification by the complexity of transaction data needed to simulate this red flag. Valid values: {sorted(SIMULATION_TYPES)}. Use null if uncertain.

## Example

Source text: "Customers who make frequent cash deposits just below the $10,000 CTR threshold, particularly across multiple branch locations on the same day."

Step 1 identification: Frequent sub-threshold cash deposits split across multiple branches.

Step 2 analysis:
{{
  "description": "Customers who make frequent cash deposits just below the $10,000 CTR threshold, particularly across multiple branch locations on the same day.",
  "product_types": ["depository"],
  "regulatory_source": "FinCEN Guidance FIN-2012-G002",
  "risk_level": "high",
  "category": "structuring",
  "simulation_type": "1A"
}}

## Output format

Return a JSON object with a single key "red_flags" containing an array of analyzed objects. Apply both steps before writing any entry. Do not duplicate indicators that appear in multiple sections of the document."""

    user_prompt = f"""Extract all AML red flags from this regulatory document using the two-step process described:

---
{document_text}
---

Return the results as a JSON object with a "red_flags" array."""

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def extract_red_flags(document_text: str, model: str | None = None) -> list[dict]:
    """Send document text to OpenAI and extract structured red flags."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("Error: OPENAI_API_KEY environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    model = model or os.environ.get("OPENAI_EXTRACTION_MODEL", DEFAULT_MODEL)
    client = OpenAI(api_key=api_key)

    messages = build_extraction_prompt(document_text)

    print(f"Sending document to {model} for extraction...")
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        response_format={"type": "json_object"},
        temperature=0.1,
    )

    content = response.choices[0].message.content
    parsed = json.loads(content)

    return parsed.get("red_flags", [])


def validate_and_build_entries(
    raw_flags: list[dict], slug: str
) -> tuple[list[dict], int]:
    """Validate extracted red flags against RedFlagSource schema.

    Returns (valid_entries, skip_count).
    """
    valid = []
    skipped = 0

    for i, flag in enumerate(raw_flags, start=1):
        entry_id = f"{slug}-{i:02d}"
        flag["id"] = entry_id

        try:
            source = RedFlagSource(**flag)
            valid.append(source.model_dump(exclude_none=True))
        except ValidationError as e:
            print(f"  Warning: Skipping entry {entry_id}: {e}", file=sys.stderr)
            skipped += 1

    return valid, skipped


def write_yaml(entries: list[dict], output_path: Path) -> None:
    """Write entries to a YAML file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w") as f:
        yaml.dump(
            entries,
            f,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )


def main() -> None:
    args = sys.argv[1:]
    force = "--force" in args
    if force:
        args.remove("--force")

    if len(args) != 1:
        print(f"Usage: {sys.argv[0]} [--force] <pdf-path-or-url>", file=sys.stderr)
        sys.exit(1)

    source = args[0]
    is_url = source.startswith(("http://", "https://"))

    # Check manifest for duplicates
    manifest = load_manifest()
    if not force and is_already_processed(source, manifest):
        print(f"Already processed: {source}")
        print("Use --force to re-extract.")
        sys.exit(0)

    # Extract text
    if is_url:
        print(f"Fetching URL: {source}")
        text = extract_text_from_url(source)
    else:
        pdf_path = Path(source)
        if not pdf_path.exists():
            print(f"Error: File not found: {source}", file=sys.stderr)
            sys.exit(1)
        if pdf_path.suffix.lower() != ".pdf":
            print(f"Error: Expected a .pdf file, got: {pdf_path.suffix}", file=sys.stderr)
            sys.exit(1)
        print(f"Extracting text from PDF: {source}")
        text = extract_text_from_pdf(source)

    if not text.strip():
        print("Error: No text extracted from source.", file=sys.stderr)
        sys.exit(1)

    print(f"Extracted {len(text)} characters of text.")

    # Generate slug and output path
    slug = source_slug(source)
    output_path = SOURCE_DIR / f"{slug}.yaml"

    if output_path.exists():
        print(f"Warning: {output_path} already exists and will be overwritten.")

    # Extract red flags via LLM
    raw_flags = extract_red_flags(text)
    print(f"LLM returned {len(raw_flags)} red flag(s).")

    # Validate and assign IDs
    entries, skipped = validate_and_build_entries(raw_flags, slug)

    if not entries:
        print("Error: No valid red flags extracted.", file=sys.stderr)
        sys.exit(1)

    # Write YAML
    write_yaml(entries, output_path)

    # Update manifest
    # Remove any existing entry for this source (for --force re-runs)
    manifest = [e for e in manifest if e.get("source") != source]
    manifest.append({
        "source": source,
        "slug": slug,
        "output_file": str(output_path.relative_to(SOURCE_DIR.parent.parent)),
        "extracted_at": datetime.now(timezone.utc).isoformat(),
    })
    save_manifest(manifest)

    print(f"\nExtracted {len(entries)} red flags from {source}")
    print(f"  → {output_path}")
    if skipped:
        print(f"  {skipped} entries skipped due to validation errors (see warnings above)")


if __name__ == "__main__":
    main()
