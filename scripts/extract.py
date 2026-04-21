#!/usr/bin/env python3
"""Extract AML red flags from PDFs or web pages using an LLM.

Usage:
    # Single source
    uv run python scripts/extract.py [--force] <pdf-path-or-url>

    # Batch mode — processes all PDFs in red_flag_sources/pdf/ and all URLs
    # in red_flag_sources/Weblinks.md, skipping already-processed sources
    uv run python scripts/extract.py [--force]
    uv run python scripts/extract.py [--force] --parallel        # 4 workers
    uv run python scripts/extract.py [--force] --parallel 8      # 8 workers

    # Range mode — process only PDFs whose serial number falls within NNN-NNN
    uv run python scripts/extract.py [--force] --range 001-005
    uv run python scripts/extract.py [--force] --range 001-005 --parallel

Outputs YAML files in data/source/ conforming to the RedFlagSource schema.
Tracks processed sources in data/source/.extracted_sources.yaml to avoid
re-processing. Use --force to bypass the duplicate check.
Requires OPENAI_API_KEY environment variable (or .env file).
"""

from __future__ import annotations

import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pdfplumber
import yaml
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from openai import OpenAI
from pydantic import ValidationError

load_dotenv()

# Add src to path so we can import redflag_mcp
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from redflag_mcp.config import RISK_LEVELS, SIMULATION_TYPES, SOURCE_DIR
from redflag_mcp.models import RedFlagSource

DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_PARALLEL_WORKERS = 4
MANIFEST_PATH = SOURCE_DIR / ".extracted_sources.yaml"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PDF_DIR = PROJECT_ROOT / "red_flag_sources" / "pdf"
WEBLINKS_PATH = PROJECT_ROOT / "red_flag_sources" / "Weblinks.md"
SOURCES_REGISTRY_PATH = PROJECT_ROOT / "red_flag_sources" / "sources.yaml"


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


def normalize_source(source: str) -> str:
    """Normalize a source identifier to a canonical form for deduplication.

    Local file paths are resolved to absolute paths so that relative and
    absolute references to the same file compare equal. URLs are returned
    unchanged.
    """
    if source.startswith(("http://", "https://")):
        return source
    return str(Path(source).resolve())


def is_already_processed(source: str, manifest: list[dict]) -> bool:
    """Check if a source has already been processed."""
    normalized = normalize_source(source)
    return any(normalize_source(entry.get("source", "")) == normalized for entry in manifest)


def load_sources_registry() -> dict:
    """Load red_flag_sources/sources.yaml, return {} if absent."""
    if not SOURCES_REGISTRY_PATH.exists():
        return {}
    with open(SOURCES_REGISTRY_PATH) as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, dict) else {}


def extract_serial_key(filename: str) -> str | None:
    """Extract leading numeric serial key from filename, e.g. '001' from '001_fincen.pdf'."""
    match = re.match(r"^(\d+)[_-]", filename)
    return match.group(1) if match else None


def get_source_url(source: str, registry: dict) -> str | None:
    """Resolve the public URL for a source.

    - Web URLs: return the URL itself.
    - PDFs: extract serial key from filename, look up in registry.
    """
    if source.startswith(("http://", "https://")):
        return source
    key = extract_serial_key(Path(source).name)
    if key and key in registry:
        return registry[key].get("url")
    return None


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

## What is a red flag?

A red flag is a description of specific, observable customer behavior or transaction activity that a financial institution employee could directly witness and that indicates potential money laundering or financial crime. It must describe what someone is *doing* — not what a regulator has decided, not what an institution is required to do, and not background information about a typology.

A valid red flag answers: "What would a compliance officer actually observe that should trigger suspicion?"

## Step 1 — Identify red flags

**Where to look first:** Scan the document for sections explicitly labeled as red flags or indicators — headings such as "Red Flags", "Risk Indicators", "Suspicious Activity Indicators", "Warning Signs", or similar. Extract from those sections first and most thoroughly.

For content outside labeled sections, apply strict criteria: only extract text that describes a specific, observable behavior or transaction pattern. Do not extract from introductory, background, enforcement, or conclusion sections.

**Handling embedded examples:** When an indicator is followed by an example clause ("For example,", "e.g.,", "such as", "including"), the example is part of that indicator — keep the full passage as one entry. Do not extract the example as a separate red flag.

**Do NOT extract the following:**
- Enforcement actions, historical cases, or examples of past violations ("OFAC has taken enforcement actions against…", "Company X was fined for…")
- SAR filing instructions or recommendations ("financial institutions should file a SAR if…", "consider filing a SAR when…")
- Regulatory directives or compliance obligations ("institutions are required to…", "banks must screen…")
- Explanations of how a typology or scheme works at a general level, without describing an observable indicator
- Document headers, section titles, introductory paragraphs, and administrative text

**Test before including:** Ask — "Could a compliance officer directly observe this at their institution?" If no, do not extract it.

## Step 2 — Analyze each red flag

For each indicator identified in Step 1, determine the following metadata:

- "description" (string, required): Copy the indicator text exactly as it appears in the source document, including any embedded example clause. Do not paraphrase, generalize, or remove any wording.
- "product_types" (list of strings): Which financial products or channels does this indicator apply to? Choose from: "depository", "credit_card", "money_transmitter", "prepaid", "securities", "insurance", "crypto", "msb", "private_banking", "correspondent_banking", "trade_finance". Include all that apply.
- "regulatory_source" (string): The full name of the issuing document or authority (e.g., "FinCEN Alert FIN-2022-Alert001", "FFIEC BSA/AML Examination Manual Appendix F").
- "risk_level" (string): Severity of the indicator. One of: {sorted(RISK_LEVELS)}. Use "high" for indicators directly tied to confirmed typologies or sanctions violations; "medium" for suspicious patterns requiring investigation; "low" for weak signals that need corroboration.
- "category" (string): The primary AML typology. Use: "structuring", "layering", "sanctions_evasion", "terrorist_financing", "fraud_nexus", "corruption", "shell_company", "trade_based_ml", "cyber_enabled", "ransomware", "virtual_currency". If multiple apply, choose the most specific.
- "simulation_type" (string or null): Classification by the complexity of transaction data needed to simulate this red flag. Valid values: {sorted(SIMULATION_TYPES)}. Use null if uncertain.

## Example

Source text: "Non-routine foreign exchange transactions that may indirectly involve sanctioned financial institutions, including transactions that are inconsistent with activity over the prior 12 months. For example, a sanctioned entity may seek to use import or export companies to conduct transactions."

**Wrong** — splitting into two entries:
1. "Non-routine foreign exchange transactions that may indirectly involve sanctioned financial institutions..."
2. "For example, a sanctioned entity may seek to use import or export companies to conduct transactions."

**Correct** — one entry with the full passage including the example:
{{
  "description": "Non-routine foreign exchange transactions that may indirectly involve sanctioned financial institutions, including transactions that are inconsistent with activity over the prior 12 months. For example, a sanctioned entity may seek to use import or export companies to conduct transactions.",
  "product_types": ["correspondent_banking", "trade_finance"],
  "regulatory_source": "FinCEN Alert FIN-2022-Alert001",
  "risk_level": "high",
  "category": "sanctions_evasion",
  "simulation_type": null
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
    raw_flags: list[dict], slug: str, source_url: str | None = None
) -> tuple[list[dict], int]:
    """Validate extracted red flags against RedFlagSource schema.

    Returns (valid_entries, skip_count).
    """
    valid = []
    skipped = 0

    for i, flag in enumerate(raw_flags, start=1):
        entry_id = f"{slug}-{i:02d}"
        flag["id"] = entry_id
        if source_url:
            flag["source_url"] = source_url

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


def parse_weblinks(path: Path) -> list[str]:
    """Parse URLs from a Weblinks.md file.

    Handles numbered list format: '1) https://...'
    Returns a list of URL strings, skipping blank lines and non-URL lines.
    """
    if not path.exists():
        return []

    urls = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            # Match optional numbering prefix: '1) ', '1. ', or bare URL
            match = re.match(r"^(?:\d+[).]\s+)?(https?://\S+)$", line)
            if match:
                urls.append(match.group(1))
    return urls


def discover_sources() -> list[str]:
    """Discover all PDF files in red_flag_sources/pdf/ and URLs in Weblinks.md."""
    sources: list[str] = []

    if PDF_DIR.exists():
        for pdf in sorted(PDF_DIR.glob("*.pdf")):
            sources.append(str(pdf))

    sources.extend(parse_weblinks(WEBLINKS_PATH))

    return sources


def process_one(source: str, force: bool, manifest: list[dict], source_url: str | None = None) -> dict | None:
    """Process a single source (PDF path or URL).

    Returns a manifest entry dict on success, or None on skip/failure.
    Does NOT write to the manifest file — the caller handles that.
    """
    source = normalize_source(source)
    if not force and is_already_processed(source, manifest):
        print(f"Skipping (already processed): {source}")
        return None

    is_url = source.startswith(("http://", "https://"))

    try:
        if is_url:
            print(f"Fetching URL: {source}")
            text = extract_text_from_url(source)
        else:
            pdf_path = Path(source)
            if not pdf_path.exists():
                print(f"Error: File not found: {source}", file=sys.stderr)
                return None
            if pdf_path.suffix.lower() != ".pdf":
                print(f"Error: Expected a .pdf file, got: {pdf_path.suffix}", file=sys.stderr)
                return None
            print(f"Extracting text from PDF: {source}")
            text = extract_text_from_pdf(source)
    except Exception as e:
        print(f"Error fetching/reading {source}: {e}", file=sys.stderr)
        return None

    if not text.strip():
        print(f"Error: No text extracted from {source}", file=sys.stderr)
        return None

    print(f"Extracted {len(text)} characters of text from {Path(source).name if not is_url else source}.")

    slug = source_slug(source)
    output_path = SOURCE_DIR / f"{slug}.yaml"

    try:
        raw_flags = extract_red_flags(text)
    except Exception as e:
        print(f"Error calling LLM for {source}: {e}", file=sys.stderr)
        return None

    print(f"LLM returned {len(raw_flags)} red flag(s) for {slug}.")

    entries, skipped = validate_and_build_entries(raw_flags, slug, source_url=source_url)

    if not entries:
        print(f"Error: No valid red flags extracted from {source}", file=sys.stderr)
        return None

    write_yaml(entries, output_path)

    manifest_entry = {
        "source": source,
        "slug": slug,
        "output_file": str(output_path.relative_to(SOURCE_DIR.parent.parent)),
        "extracted_at": datetime.now(timezone.utc).isoformat(),
    }

    print(f"\nExtracted {len(entries)} red flags from {source}")
    print(f"  → {output_path}")
    if skipped:
        print(f"  {skipped} entries skipped due to validation errors")

    return manifest_entry


def run_batch(force: bool, workers: int | None, serial_range: tuple[int, int] | None = None) -> None:
    """Discover and process all sources in batch mode."""
    sources = discover_sources()

    if serial_range is not None:
        start, end = serial_range
        sources = [
            s for s in sources
            if (key := extract_serial_key(Path(s).name)) is not None and start <= int(key) <= end
        ]
        print(f"Range filter {start:03d}-{end:03d}: {len(sources)} PDF(s) matched.")

    if not sources:
        print("No sources found in red_flag_sources/pdf/ or red_flag_sources/Weblinks.md.")
        return

    manifest = load_manifest()
    registry = load_sources_registry()

    pending = [s for s in sources if force or not is_already_processed(s, manifest)]
    skipped_count = len(sources) - len(pending)

    print(f"Found {len(sources)} source(s): {len(pending)} to process, {skipped_count} already done.")
    if not pending:
        print("Nothing to do. Use --force to re-extract all sources.")
        return

    new_entries: list[dict] = []

    if workers is None:
        # Sequential
        for source in pending:
            url = get_source_url(source, registry)
            entry = process_one(source, force=force, manifest=manifest, source_url=url)
            if entry:
                new_entries.append(entry)
    else:
        # Parallel
        print(f"Running with {workers} parallel worker(s).")
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(process_one, source, force, manifest, get_source_url(source, registry)): source
                for source in pending
            }
            for future in as_completed(futures):
                source = futures[future]
                try:
                    entry = future.result()
                    if entry:
                        new_entries.append(entry)
                except Exception as e:
                    print(f"Unexpected error processing {source}: {e}", file=sys.stderr)

    if new_entries:
        # Reload manifest to pick up any concurrent single-source runs, then upsert
        final_manifest = load_manifest()
        new_sources = {e["source"] for e in new_entries}
        final_manifest = [e for e in final_manifest if e.get("source") not in new_sources]
        final_manifest.extend(new_entries)
        save_manifest(final_manifest)
        print(f"\nBatch complete. {len(new_entries)} source(s) processed.")


def main() -> None:
    args = sys.argv[1:]

    force = "--force" in args
    if force:
        args.remove("--force")

    # Parse --parallel [N]
    workers: int | None = None
    if "--parallel" in args:
        idx = args.index("--parallel")
        args.pop(idx)
        # Check if next arg is an integer
        if idx < len(args) and args[idx].isdigit():
            workers = int(args.pop(idx))
        else:
            workers = DEFAULT_PARALLEL_WORKERS

    # Parse --range NNN-NNN
    serial_range: tuple[int, int] | None = None
    if "--range" in args:
        idx = args.index("--range")
        args.pop(idx)
        if idx < len(args):
            range_str = args.pop(idx)
            match = re.fullmatch(r"(\d+)-(\d+)", range_str)
            if not match:
                print("Error: --range must be in format NNN-NNN (e.g. 001-005)", file=sys.stderr)
                sys.exit(1)
            start, end = int(match.group(1)), int(match.group(2))
            if start > end:
                print("Error: --range start must be <= end", file=sys.stderr)
                sys.exit(1)
            serial_range = (start, end)
        else:
            print("Error: --range requires an argument (e.g. --range 001-005)", file=sys.stderr)
            sys.exit(1)

    if len(args) == 0:
        # Batch mode
        run_batch(force=force, workers=workers, serial_range=serial_range)
    elif len(args) == 1:
        # Single-source mode
        if workers is not None:
            print("Note: --parallel is ignored in single-source mode.", file=sys.stderr)
        if serial_range is not None:
            print("Note: --range is ignored in single-source mode.", file=sys.stderr)

        source = args[0]
        manifest = load_manifest()
        if not force and is_already_processed(source, manifest):
            print(f"Already processed: {source}")
            print("Use --force to re-extract.")
            sys.exit(0)

        registry = load_sources_registry()
        url = get_source_url(source, registry)
        entry = process_one(source, force=force, manifest=manifest, source_url=url)
        if entry is None:
            sys.exit(1)

        # Update manifest
        updated = [e for e in manifest if e.get("source") != source]
        updated.append(entry)
        save_manifest(updated)
    else:
        print(
            f"Usage:\n"
            f"  {sys.argv[0]} [--force] <pdf-path-or-url>                    # single source\n"
            f"  {sys.argv[0]} [--force] [--parallel [N]]                     # batch mode\n"
            f"  {sys.argv[0]} [--force] --range NNN-NNN [--parallel [N]]     # range mode",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
