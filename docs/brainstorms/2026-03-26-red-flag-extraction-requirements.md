---
date: 2026-03-26
topic: red-flag-extraction
---

# Red Flag Extraction from PDFs and Weblinks

## Problem Frame

The redflag-mcp project needs a populated database of AML red flags to be useful. Regulatory guidance containing red flags is published as PDFs (e.g., FinCEN alerts) and web pages (e.g., FFIEC manual appendices). Manually reading these documents and hand-writing YAML entries is slow and error-prone. A reusable extraction script that reads a PDF or URL, identifies red flags using an LLM, and outputs structured YAML directly into `data/source/` eliminates this bottleneck and makes it easy to add new regulatory sources as they're published.

## Requirements

- R1. A script (`scripts/extract.py`) accepts a PDF file path or a URL as input and outputs a YAML file in `data/source/` containing the extracted red flags.
- R2. For PDFs, the script extracts raw text locally (using `pdfplumber`) and sends it to an LLM for structured extraction. No vision/image models needed.
- R3. For URLs, the script fetches and strips the page content to plain text, then sends it through the same LLM extraction pipeline as PDFs.
- R4. The LLM prompt instructs the model to identify all distinct AML red flags in the document and return each as a structured object with: `id`, `description`, `product_types`, `industry_types`, `customer_profiles`, `geographic_footprints`, `regulatory_source`, `risk_level`, and `category`.
- R5. The `id` field is auto-generated as a slug derived from the source document and a sequence number (e.g., `fincen-russian-sanctions-2022-01`).
- R6. Output YAML conforms exactly to the `RedFlagSource` schema defined in `models.py`, so `ingest.py` can process it without modification.
- R7. The output file is named after the source document (e.g., `fincen-russian-sanctions-2022.yaml`) and written to `data/source/`.
- R8. The script uses the same OpenAI API configuration as the rest of the project (`OPENAI_API_KEY` env var, configurable model via `OPENAI_EXTRACTION_MODEL` defaulting to `gpt-4o-mini`).

## Success Criteria

- Running `scripts/extract.py` on the existing FinCEN PDF produces a valid YAML file with 10+ red flag entries that pass `RedFlagSource` validation.
- Running `scripts/extract.py` on a URL containing red flags produces equivalent output.
- The output YAML can be fed directly to `scripts/ingest.py` without errors.
- A compliance professional reviewing the extracted red flags would recognize them as accurate representations of the source document.

## Scope Boundaries

- The script extracts and structures; it does not embed or store. That's `ingest.py`'s job.
- No interactive review/edit UI. The user reviews the YAML file after extraction if they want to refine it.
- No batch processing of multiple files in a single run (though this would be a trivial future addition).
- No OCR for scanned PDFs — assumes PDFs have selectable text.
- Web scraping is best-effort; pages behind authentication or heavy JavaScript rendering are out of scope.

## Key Decisions

- **LLM-based extraction over rule-based parsing**: Regulatory documents vary widely in format. LLM extraction is robust across different layouts and can identify red flags even when they're embedded in prose rather than bullet lists.
- **Extract metadata during extraction, not at ingestion**: The LLM has full document context during extraction (e.g., it knows the source is a FinCEN alert about Russian sanctions), making metadata tagging more accurate than the context-free tagging in `ingest.py`.
- **Write directly to `data/source/`**: No staging directory. The user can review the YAML before running `ingest.py`.
- **Text extraction then LLM, not direct PDF-to-LLM**: Keeps costs low, avoids vision model dependency, and `pdfplumber` is already available in the environment.

## Dependencies / Assumptions

- `pdfplumber` is available (confirmed installed in the environment).
- `OPENAI_API_KEY` must be set for the LLM extraction call.
- Web page text extraction needs an HTTP client and HTML-to-text conversion (e.g., `httpx` + `beautifulsoup4`, or a simpler approach like `defuddle`).
- The `RedFlagSource` model from `models.py` must be defined before this script can validate output (Unit 1 dependency from the existing plan).

## Outstanding Questions

### Deferred to Planning

- [Affects R3][Needs research] Best library for web page text extraction — `httpx` + `beautifulsoup4`, `trafilatura`, or `defuddle` CLI. Should balance extraction quality with dependency weight.
- [Affects R4][Technical] Optimal prompt structure for the LLM extraction call — whether to send the full document in one call or chunk it. The FinCEN PDF is ~4K tokens of extracted text, well within context limits, but longer documents may need chunking.
- [Affects R8][Technical] Whether `gpt-4o-mini` is sufficient for extraction quality or whether a larger model is needed. Can be validated empirically during implementation.

## Next Steps

-> `/ce:plan` for structured implementation planning
