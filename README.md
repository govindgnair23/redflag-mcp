# redflag-mcp

MCP server exposing AML red flag knowledge as queryable tools. Compliance officers ask natural-language questions; the server returns relevant, sourced red flags from either a local LanceDB vector store or a packaged SQLite FTS5 corpus.

## Hosted Connector

Public users should start with the hosted MCP URL:

```text
https://redflag-mcp.up.railway.app/mcp
```

Add that URL in a hosted MCP client, enable the connector, and ask AML red flag research questions such as:

```text
What red flags apply to TBML invoice mismatch?
Which red flags cover bulk cash movement to Mexico?
List source coverage for the corpus.
```

Public hosted mode is not for confidential customer, transaction, institution, or investigation details. User prompts are sent to the hosted MCP service operator and the host client. Use local desktop or institution-hosted deployments for sensitive institution-specific context.

The hosted connector is backed by a verified packaged corpus. End users do not need Python, repository setup, package downloads, ingestion, OpenAI keys, or environment variables. Operators should use [docs/hosted-deployment.md](docs/hosted-deployment.md) for Railway deployment, corpus activation, rollback, logging, and validation.

## Overview

Nine distinct workflows:

1. **URL pipeline** — download URLs, optionally inspect local captures, then extract red flags
2. **Source harvesting** — bulk-download PDFs and web pages from a catalog CSV into `sources.yaml`
3. **Extraction** — pull AML red flags out of PDFs or web pages using an LLM and save them as YAML
4. **Verification** — second-stage LLM classifier removes false positives (compliance guidance, regulatory instructions, case narratives) from extracted candidates
5. **Source registry** — rebuild `red_flag_sources/registry.csv`, the audit ledger for extracted, downloaded, and not-downloaded sources
6. **Ingestion** — embed the YAML files and load them into the local vector database
7. **Corpus packaging** — build a versioned SQLite FTS5 package for offline lexical runtime use
8. **Hosted deployment** — run the ASGI MCP service from a verified corpus package at one public `/mcp` URL
9. **Query** — MCP server answers search and filtering requests against the configured local or hosted store

---

## URL Pipeline

Use `scripts/pipeline.py` for day-to-day source onboarding from URLs. The `download` and `run` subcommands accept **either a URL file or a single URL** as the positional argument. It supports both a one-shot workflow and a review checkpoint between download and extraction.

For batches, create a plain text file with one URL per line:

```text
https://example.gov/report.pdf
https://example.gov/red-flag-guidance
```

Blank lines and non-HTTP(S) lines are skipped.

### One-shot download and extraction

```bash
# From a URL file
uv run python scripts/pipeline.py run urls.txt

# Or directly with a single URL
uv run python scripts/pipeline.py run https://example.gov/report.pdf
```

Use this when you trust the source list and want to download each URL, register it in `red_flag_sources/sources.yaml`, extract red flags, update `data/source/.extracted_sources.yaml`, and rebuild `red_flag_sources/registry.csv`.

### Download, inspect, then extract

```bash
# Download PDFs/web captures and update sources.yaml + registry.csv
uv run python scripts/pipeline.py download urls.txt
uv run python scripts/pipeline.py download https://example.gov/report.pdf

# Inspect red_flag_sources/pdf/ and red_flag_sources/markdown/, then extract downloaded rows
uv run python scripts/pipeline.py extract
```

Use the two-step flow when you want to inspect Jina Reader markdown captures or downloaded PDFs before spending OpenAI extraction calls.

### Options

```bash
# Bypass registry deduplication and re-download/re-extract
uv run python scripts/pipeline.py run urls.txt --force

# Extract downloaded sources in parallel; default is sequential unless --parallel is present
uv run python scripts/pipeline.py extract --parallel
uv run python scripts/pipeline.py extract --parallel 8
uv run python scripts/pipeline.py run urls.txt --parallel 4

# Skip the verification step entirely
uv run python scripts/pipeline.py extract --no-verify
uv run python scripts/pipeline.py run urls.txt --no-verify

# Force the handcrafted verification prompt (ignores verifier_prompt.json if present)
uv run python scripts/pipeline.py extract --prompt handcrafted
uv run python scripts/pipeline.py run urls.txt --prompt handcrafted
```

Verification runs by default on both `extract` and `run`. The optimized prompt (`data/verifier_prompt.json`) is used when available; `--prompt handcrafted` forces the built-in prompt for comparison. See [Red Flag Verification](#red-flag-verification) for details.

Deduplication uses `red_flag_sources/registry.csv` by `source_url`. Re-run `scripts/build_registry.py` first if you manually edited `sources.yaml`, catalog CSVs, or YAML source files and need the pipeline to see the latest status.

---

## Source Harvesting

`scripts/harvest_sources.py` is the canonical download utility. It accepts **either a catalog CSV path or a single http(s) URL** as the positional argument, classifies each URL as a PDF or web page, downloads the file, and registers it in `red_flag_sources/sources.yaml`. No extraction is triggered — that is `pipeline.py`'s job.

```bash
# Bulk download from a catalog CSV
uv run python scripts/harvest_sources.py red_flag_sources/Global_AML_CFT_Sanctions_Red_Flag_Catalog.csv

# Download a single URL
uv run python scripts/harvest_sources.py https://example.gov/report.pdf

# Re-download even if already registered
uv run python scripts/harvest_sources.py --force https://example.gov/report.pdf
```

**What it does:**

1. Detects whether the positional argument is a URL or a CSV path
2. **CSV mode** — reads the `Direct URL` column from each row; skips blank, malformed, or already-registered URLs
3. **URL mode** — skips immediately if the URL is already registered (use `--force` to override)
4. Classifies each URL as PDF via path heuristics (`.pdf` suffix, `/download`, `/file`) — falls back to an HTTP HEAD check for ambiguous cases
5. Downloads PDFs to `red_flag_sources/pdf/NNN.pdf`
6. Fetches web pages via the [Jina Reader API](https://r.jina.ai/) and saves cleaned markdown to `red_flag_sources/markdown/NNN.md`
7. Appends each new entry to `sources.yaml`
8. In CSV mode, prints a final summary: PDFs downloaded, web pages fetched, skipped, failed

The script is **idempotent** — re-running against the same CSV or URL produces no new files or registry entries (unless `--force` is set). Per-URL failures are logged and skipped without aborting a CSV run.

```
red_flag_sources/
  Global_AML_CFT_Sanctions_Red_Flag_Catalog.csv   # input catalog (~218 URLs)
  sources.yaml                                      # registry of all harvested URLs
  pdf/                                              # downloaded PDFs (gitignored via *.pdf)
  markdown/                                         # Jina Reader captures (gitignored)
```

After harvesting, rebuild the status registry and pass downloaded files to extraction:

```bash
uv run python scripts/build_registry.py

# Extract red flags from all newly downloaded PDFs
uv run python scripts/extract.py --parallel

# Or target a specific serial range
uv run python scripts/extract.py --range 039-060 --parallel
```

**When to use which script:**

| Goal | Use |
|---|---|
| Download a catalog CSV or a single URL (no extraction) | `harvest_sources.py` |
| Download + extract from a URL file or single URL in one step | `pipeline.py run` |
| Extract from already-downloaded local files | `extract.py` |

> **Note:** `sources.yaml` is the shared URL registry for `pipeline.py`, `harvest_sources.py`, and `build_sources_registry.py`. Do not run these scripts concurrently — each can overwrite `sources.yaml` after updating it.

### Web-page capture via Jina Reader

Web pages (non-PDF URLs) are fetched through [**Jina Reader**](https://jina.ai/reader/), a hosted service that takes a URL, strips navigation/footer/scripts/ads, and returns clean, LLM-ready markdown.

- **Endpoint**: `https://r.jina.ai/<url>` — prepend the target URL to capture it
- **Caller**: `fetch_web()` in `scripts/harvest_sources.py`; also used internally by `pipeline.py` via `download_single_url()`
- **Auth**: used unauthenticated in this repo. Jina's free tier works without an API key; supplying one as a `Bearer` token raises rate limits if you hit them
- **Why this service**: regulator pages mix substance with heavy chrome (menus, related-links, cookie banners). Jina Reader gives the LLM only the article body, which materially improves extraction quality and reduces token spend

If a captured markdown file in `red_flag_sources/markdown/` looks empty or wrong, inspect it before extraction — the page may have been blocked, paywalled, or rendered client-side. Re-run with `--force` after fixing the URL.

---

## Extraction Pipeline

`scripts/extract.py` takes a **downloaded regulatory document** (local PDF or markdown file path), sends its text to an OpenAI model, and writes a structured YAML file into `data/source/`. Each extracted entry includes a `source_url` linking back to the original document (resolved from `sources.yaml`).

> `extract.py` no longer downloads URLs. To fetch a URL, use `harvest_sources.py` (download only) or `pipeline.py run` (download + extract). This keeps each script's responsibility clean.

### Prerequisites

```bash
uv sync --extra dev
export OPENAI_API_KEY=sk-...
```

### Adding sources in bulk (recommended workflow)

Use `scripts/pipeline.py` for new URL lists:

```bash
uv run python scripts/pipeline.py download urls.txt
uv run python scripts/pipeline.py extract --parallel
```

This downloads into `red_flag_sources/pdf/` or `red_flag_sources/markdown/`, updates `sources.yaml`, extracts downloaded registry rows, updates `.extracted_sources.yaml`, and rebuilds `registry.csv`.

For catalog CSVs, use `scripts/harvest_sources.py` first, then `scripts/extract.py`.

### Manual PDF workflow

PDFs are stored in `red_flag_sources/pdf/` and should be named with a zero-padded serial prefix:

```
red_flag_sources/pdf/
  001_fincen_alert_russian_sanctions_evasion.pdf
  002_ffiec_bsa_aml_examination_manual.pdf
  003_fatf_guidance_virtual_assets.pdf
```

Each serial number maps to a public URL for the source document in `red_flag_sources/sources.yaml`. For the legacy manual flow, maintain that mapping in `red_flag_sources/pdflinks.txt` — one URL per line, in serial order:

```
# FinCEN Russian Sanctions Evasion Alert
https://fincen.gov/sites/default/files/2022-06/Alert%20FIN-2022-Alert001_508C.pdf

# FFIEC BSA/AML Examination Manual
https://bsaaml.ffiec.gov/manual

# FATF Guidance on Virtual Assets
https://www.fatf-gafi.org/...
```

Blank lines and lines starting with `#` are ignored. After editing `pdflinks.txt`, regenerate `sources.yaml` and `registry.csv`:

```bash
uv run python scripts/build_sources_registry.py
uv run python scripts/build_registry.py
```

Then run batch extraction:

```bash
uv run python scripts/extract.py --parallel
```

Only new (unprocessed) PDFs are extracted — previously processed sources are skipped automatically.

### Batch extraction commands

```bash
# Sequential batch
uv run python scripts/extract.py

# Parallel batch (4 workers by default)
uv run python scripts/extract.py --parallel

# Parallel batch with custom worker count
uv run python scripts/extract.py --parallel 8

# Force re-extract everything
uv run python scripts/extract.py --force --parallel

# Process only PDFs in a serial range (e.g. 001 through 005)
uv run python scripts/extract.py --range 001-005

# Range + parallel
uv run python scripts/extract.py --range 001-005 --parallel

# Force re-extract a range
uv run python scripts/extract.py --force --range 001-005 --parallel

# Skip shaping (descriptions stay verbatim from extraction; useful for A/B comparison)
uv run python scripts/extract.py --no-shape --parallel

# Skip verification (raw extraction output, no false-positive filtering)
uv run python scripts/extract.py --no-verify --parallel

# Skip both passes (raw extractor output only)
uv run python scripts/extract.py --no-shape --no-verify --parallel

# Use handcrafted verifier prompt instead of optimized (useful for A/B comparison)
uv run python scripts/extract.py --prompt handcrafted --parallel
```

> **Note:** `--range` applies only to numbered PDFs. Web URLs in `Weblinks.md` are excluded when a range is active.

### Single source (ad hoc)

```bash
# Extract from a local PDF
uv run python scripts/extract.py red_flag_sources/pdf/001_fincen_alert.pdf

# Extract from a local markdown capture
uv run python scripts/extract.py red_flag_sources/markdown/061.md

# Re-extract a source that was already processed
uv run python scripts/extract.py --force red_flag_sources/pdf/001_fincen_alert.pdf

# Re-extract without verification
uv run python scripts/extract.py --force --no-verify red_flag_sources/pdf/001_fincen_alert.pdf

# Re-extract using handcrafted prompt
uv run python scripts/extract.py --force --prompt handcrafted red_flag_sources/pdf/001_fincen_alert.pdf
```

`extract.py` requires the file to exist locally already. To fetch a URL first:

```bash
# Download only, then extract separately
uv run python scripts/harvest_sources.py https://example.gov/report.pdf
uv run python scripts/extract.py red_flag_sources/pdf/NNN.pdf

# Or download + extract in one step
uv run python scripts/pipeline.py run https://example.gov/report.pdf
```

For single-source PDFs, make sure `sources.yaml` maps the file's serial prefix to the public URL before extraction so the extractor can populate `source_url` in the output. If you maintain the legacy `pdflinks.txt` file, run `build_sources_registry.py` and then `build_registry.py` first.

### What it does

1. **Reads the document** — extracts text from the local PDF via pdfplumber, or reads the body of a Jina Reader markdown capture
2. **Extracts** — prompts the configured OpenAI model (override with `OPENAI_EXTRACTION_MODEL`) to extract every distinct AML red flag indicator and tag all metadata fields as structured JSON. Descriptions are returned in source-faithful wording.
3. **Shapes** — a second LLM call rewrites only the `description` field: prepends a noun subject when missing, merges dependent explanatory sentences, generalizes case-specific numbers, and strips stray named facts. Skip with `--no-shape`. See [Red Flag Shaping](#red-flag-shaping) below.
4. **Verifies** — a third LLM call classifies each candidate as a genuine red flag or false positive (compliance guidance, regulatory instruction, etc.) and removes false positives. Skip with `--no-verify`. See [Red Flag Verification](#red-flag-verification) below.
5. **Infers regulator** — when a `source_url` is available, the regulator is inferred deterministically from the URL domain (e.g. `ofac.treasury.gov` → `OFAC`), overriding LLM extraction
6. **Validates** — each returned flag is checked against the `RedFlagSource` schema; invalid entries are skipped with a warning
7. **Writes YAML** — saves to `data/source/<slug>.yaml`, one entry per red flag
8. **Updates the manifest** — records the source in `data/source/.extracted_sources.yaml` to prevent re-processing
9. **Rebuilds the source registry** — updates `red_flag_sources/registry.csv` after successful batch or single-source extraction

### Output schema

Each entry in the YAML file has the following fields:

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | string | yes | Unique identifier, e.g. `001-fincen-alert-01` |
| `description` | string | yes | Standalone description of the red flag indicator |
| `source_url` | string | no | Public URL of the source document |
| `product_types` | list[string] | no | Financial products this applies to (e.g. `depository`, `crypto`, `msb`) |
| `industry_types` | list[string] | no | Customer industries or sectors this applies to (e.g. `oil_and_gas`, `government_benefits`) |
| `customer_profiles` | list[string] | no | Customer archetypes this applies to (e.g. `small_business`, `charity_or_nonprofit`) |
| `geographic_footprints` | list[string] | no | Relevant geographies or corridors (e.g. `southwest_border`, `mexico`) |
| `regulatory_source` | string | no | Source document name or authority (e.g. `FinCEN Alert FIN-2022-Alert001`) |
| `regulator` | string | no | Abbreviated issuing authority (e.g. `FinCEN`, `OFAC`, `FATF`). Populated at extraction; auto-tagged by write-back when absent. |
| `regulator_jurisdiction` | string | no | Canonical jurisdiction code deterministically derived from `regulator` (e.g. `US`, `FR`, `SG`, `AU`, `GB`, `EU`). Not normally extracted by the LLM. |
| `issued_date` | string | no | Publication date of the source document (ISO 8601: YYYY-MM-DD, YYYY-MM, or YYYY). |
| `risk_level` | string | no | `high`, `medium`, or `low` |
| `category` | string | no | AML typology (e.g. `structuring`, `sanctions_evasion`, `shell_company`) |
| `simulation_type` | string | no | Optional simulation complexity code (e.g. `1A`, `2B`) |
| `typology_family` | list[string] | no | Higher-level AML typology families (e.g. `trade_based_money_laundering`, `fraud_proceeds`) |
| `transaction_patterns` | list[string] | no | Observable behavioral patterns (e.g. `structuring`, `trade_document_manipulation`) |
| `key_terms` | list[string] | no | Short searchable phrases, instruments, thresholds, or acronyms (e.g. `TBML`, `CTR`, `cashier's check`) |

`regulator` and `issued_date` are requested during extraction. `regulator_jurisdiction` is derived in code from `regulator`; if the regulator is missing or unmapped, it stays unset and ingestion logs a warning. `typology_family`, `transaction_patterns`, and `key_terms` are added to existing YAML source files by running `scripts/ingest.py --write-back-yaml` (see [Enriching YAML source files](#enriching-yaml-source-files-write-back) below).

### Deduplication

`data/source/.extracted_sources.yaml` tracks every processed source by its canonical path or URL. Sources already in the manifest are skipped in both batch and single-source mode. Use `--force` to re-extract a source regardless.

---

## Red Flag Shaping

Between extraction and verification, a shaping pass rewrites only the `description` field on each candidate so the corpus reads consistently. It does not touch metadata.

### What it does

- Prepends a concrete noun subject ("Customers," "Entities or individuals," "Transactions," etc.) when the source wording starts with a verb phrase or orphaned predicate.
- Merges dependent explanatory sentences ("Such…", "Similarly…", "These…") into the preceding sentence so each indicator reads as one unit.
- Generalizes case-specific dollar amounts, percentages, and counts (`"$100 million"` → `"large sums (e.g., $100 million)"`; `"two exchanges"` → `"exchanges"`), while leaving structural numbers like CTR thresholds alone.
- Strips named persons, companies, or one-off facts that slipped through extraction.

The shaper uses the same default model as extraction (`gpt-5.4-mini`); override with `OPENAI_SHAPING_MODEL`.

### Skipping shaping

```bash
# Single source — keep descriptions verbatim from extraction
uv run python scripts/extract.py --force --no-shape red_flag_sources/pdf/048*.pdf

# Skip both shaping and verification (raw extractor output)
uv run python scripts/extract.py --force --no-shape --no-verify red_flag_sources/pdf/048*.pdf
```

Use `--no-shape` when debugging the extraction prompt or comparing shaped vs. raw output.

---

## Red Flag Verification

The extraction pipeline includes a third-stage LLM verifier that filters out false positives — items that look like red flags but are actually compliance guidance, regulatory instructions, case narratives, or general background. The verifier makes a single OpenAI call per document batch.

### How it works

After `extract_red_flags()` returns candidate items, `verify_red_flags()` sends all descriptions to the LLM in one call. Each candidate is classified as a genuine red flag (`true`) or not (`false`). Only candidates classified as `true` proceed to validation and YAML output.

### Controlling which prompt is used

By default the verifier loads `data/verifier_prompt.json` (the DSPy-optimized prompt) when it exists, and falls back to the handcrafted prompt otherwise. Use `--prompt` to override:

```bash
# Force the handcrafted prompt even when verifier_prompt.json exists
uv run python scripts/extract.py --prompt handcrafted red_flag_sources/pdf/001*.pdf

# Explicitly request the optimized prompt (default behaviour, but makes intent clear)
uv run python scripts/extract.py --prompt optimized red_flag_sources/pdf/001*.pdf
```

### Skipping verification

```bash
# Extract without the verification step at all
uv run python scripts/extract.py --force --no-verify red_flag_sources/pdf/048*.pdf
```

Use `--no-verify` when you want raw extraction output or are debugging the extraction prompt.

### Evaluating verifier accuracy

`scripts/eval_verifier.py` measures verifier performance against hand-labelled data in `data/source/labelled/`. Each labelled YAML file contains items with a `flag: True/False` field.

```bash
# Run eval with the active prompt (optimized if available, else handcrafted)
uv run python scripts/eval_verifier.py

# Force the handcrafted prompt for comparison
uv run python scripts/eval_verifier.py --prompt handcrafted

# A/B comparison in one go
uv run python scripts/eval_verifier.py --prompt handcrafted
uv run python scripts/eval_verifier.py --prompt optimized

# Test a specific model
uv run python scripts/eval_verifier.py --model gpt-4o

# Output as JSON for programmatic consumption
uv run python scripts/eval_verifier.py --json
```

The eval reports precision, recall, F1, accuracy, and confusion matrix for both the verifier and a baseline (no verification — all items classified as True). The output header shows which prompt was used.

### Optimizing the verifier prompt with DSPy

`scripts/optimize_verifier.py` uses [DSPy](https://dspy.ai/) to find the best verifier prompt by training on the labelled dataset. It uses `BootstrapFewShotWithRandomSearch` to optimize few-shot demos and instructions.

```bash
# Install the optimize extra
uv sync --extra optimize

# Run optimization (uses gpt-5.4-nano by default)
uv run python scripts/optimize_verifier.py

# Use a different model or strategy
uv run python scripts/optimize_verifier.py --model openai/gpt-4o-mini
uv run python scripts/optimize_verifier.py --strategy predict   # direct classification
uv run python scripts/optimize_verifier.py --strategy cot       # chain-of-thought (default)
uv run python scripts/optimize_verifier.py --max-demos 6
```

The optimized prompt is saved to `data/verifier_prompt.json`. Once this file exists, `build_verification_prompt()` automatically loads and uses it instead of the handcrafted prompt. Delete the file to revert to the handcrafted prompt.

After optimization, re-run the eval to confirm improvement:

```bash
uv run python scripts/eval_verifier.py
```

### Adding labelled data

To improve the verifier, add more labelled examples in `data/source/labelled/`. Each file follows the standard YAML source format with an additional `flag` field:

```yaml
- id: example-01
  description: "Customer structures transactions below reporting thresholds."
  flag: True    # genuine red flag
  # ... other fields ...

- id: example-02
  description: "The organization should conduct an OFAC risk assessment."
  flag: False   # compliance guidance, not a red flag
  # ... other fields ...
```

After adding labelled data, re-run optimization and eval to update the verifier.

---

## Source Registry

`scripts/build_registry.py` rebuilds `red_flag_sources/registry.csv` from scratch. The registry is a human-readable audit ledger across three states:

| Status | Meaning |
|---|---|
| `extracted` | A YAML file exists in `data/source/` and extraction metadata is available |
| `downloaded` | The URL is present in `sources.yaml`, but no extracted YAML row covers it yet |
| `not_downloaded` | The URL appears in the catalog CSVs, but is not present in `sources.yaml` |

Run it manually after editing catalog CSVs, `sources.yaml`, or extracted YAML files outside the normal scripts:

```bash
uv run python scripts/build_registry.py
```

You usually do not need to run it after `pipeline.py extract` or `extract.py`; both rebuild the registry after successful extraction. `pipeline.py download` rebuilds it after each successful download so newly captured URLs appear as `downloaded`.

The registry powers pipeline deduplication and extraction auto-discovery:

- `pipeline.py download` skips URLs already present in `registry.csv` unless `--force` is used.
- `pipeline.py extract` finds rows with `status == "downloaded"` and extracts their local PDF or markdown files.

---

## Ingestion

After extraction, embed the YAML files and load them into the vector database:

```bash
uv run python scripts/ingest.py
```

For the initial local corpus, ingest only the three target files:

```bash
uv run python scripts/ingest.py \
  data/source/001_federal_child_nutrition_fraud.yaml \
  data/source/002_oil_smuggling_cartels.yaml \
  data/source/003_bulk_cash_smuggling_repatriation.yaml
```

This generates embeddings with `nomic-embed-text-v1.5` and upserts records into LanceDB at `data/vectors/`. Run ingestion before connecting the MCP server to a desktop client; the embedding model downloads on first use and is better cached during ingestion than during server startup.

`OPENAI_API_KEY` is optional for ingestion. When it is set, ingestion can auto-tag missing metadata into the derived LanceDB records. When it is not set, ingestion preserves available YAML metadata and leaves missing rich consultation fields empty. Source YAML files are not rewritten by normal ingestion.

### Enriching YAML source files (write-back)

To enrich source YAML files with `typology_family`, `transaction_patterns`, `key_terms`, `regulator`, `regulator_jurisdiction`, and `issued_date` — fields used for offline keyword search and faceted filtering — run ingestion with `--write-back-yaml`:

```bash
export OPENAI_API_KEY=sk-...
uv run python scripts/ingest.py --write-back-yaml data/source/001_federal_child_nutrition_fraud.yaml
```

Write-back supports the same batch selection styles as extraction:

```bash
# All visible YAML files in data/source/
uv run python scripts/ingest.py --write-back-yaml

# Multiple explicit YAML files
uv run python scripts/ingest.py --write-back-yaml \
  data/source/001_federal_child_nutrition_fraud.yaml \
  data/source/002_oil_smuggling_cartels.yaml

# Serial range by source filename prefix
uv run python scripts/ingest.py --write-back-yaml --range 001-003

# Parallel file-level write-back (4 workers by default, or pass a count)
uv run python scripts/ingest.py --write-back-yaml --range 001-003 --parallel
uv run python scripts/ingest.py --write-back-yaml --parallel 8
```

This enriches each selected source file in-place and exits without updating the vector database. Existing metadata is not overwritten by the LLM; only missing fields are requested, and deterministic fields such as `regulator_jurisdiction` are derived in code. After write-back, re-run normal ingestion to load the enriched records:

```bash
uv run python scripts/ingest.py data/source/001_federal_child_nutrition_fraud.yaml
```

> **Note:** If you deploy this change against an existing `data/vectors/` store, delete the store and re-ingest from scratch so the new columns (`typology_family`, `transaction_patterns`, `key_terms`, `regulator`, `regulator_jurisdiction`, `issued_date`) are present in the LanceDB schema:
> ```bash
> rm -rf data/vectors/
> uv run python scripts/ingest.py
> ```

---

## Corpus Packaging

Maintainers can build a versioned, verifiable SQLite FTS5 corpus package from approved YAML records:

```bash
uv run python scripts/build_corpus.py \
  --output-dir dist/corpus \
  --version 2026.04.29 \
  --all-sources

# Or build a curated corpus from explicit YAML files
uv run python scripts/build_corpus.py \
  --output-dir dist/corpus \
  --version 2026.04.29 \
  data/source/001_federal_child_nutrition_fraud.yaml \
  data/source/002_oil_smuggling_cartels.yaml \
  data/source/003_bulk_cash_smuggling_repatriation.yaml

uv run python scripts/verify_corpus.py dist/corpus/redflag-corpus-2026.04.29.zip
```

The package contains `manifest.json` and `redflags.sqlite`. The manifest records schema version, build timestamp, source record hashes, file hashes, record/source counts, and source redistribution metadata. Source documents are treated as URL-only unless `data/lexicon/source_metadata.yaml` explicitly clears them for bundling.

The current SQLite lexical corpus schema version is `3`. Rebuild older corpus packages after schema changes that add stored fields or filters.

Run the hosted retrieval smoke benchmark before publishing a corpus package:

```bash
uv run python scripts/evaluate_retrieval.py \
  --corpus dist/corpus/redflag-corpus-2026.04.29.zip \
  --benchmark data/eval/hosted_retrieval_queries.yaml
```

This benchmark checks representative alias, geography, typology, product/channel, and source-specific queries against the lexical corpus. It is a launch gate, not proof of broad AML retrieval quality.

### Running from a corpus

The server can run directly against a built SQLite corpus without loading the embedding model:

```bash
REDFLAG_CORPUS_PATH=dist/corpus/redflags.sqlite uv run python -m redflag_mcp
```

It can also verify and install a ZIP package into a local corpus cache:

```bash
REDFLAG_CORPUS_PACKAGE=dist/corpus/redflag-corpus-2026.04.29.zip \
REDFLAG_CORPUS_CACHE_DIR=~/.redflag-mcp \
uv run python -m redflag_mcp
```

For release-index driven activation:

```bash
REDFLAG_CORPUS_RELEASE_INDEX=dist/corpus/releases.json \
REDFLAG_CORPUS_VERSION=2026.04.29 \
REDFLAG_CORPUS_CACHE_DIR=~/.redflag-mcp \
uv run python -m redflag_mcp
```

Set `REDFLAG_CORPUS_AUTO_UPDATE=0` to reuse the active cached corpus without checking the package or release index. When no corpus environment variables are set, the server falls back to the LanceDB vector store at `data/vectors/`.

---

## MCP Server

```bash
# Start server (stdio mode, for Claude Desktop / Claude Code)
uv run python -m redflag_mcp

# Start in MCP inspector
uv run mcp dev src/redflag_mcp/server.py

# Start as HTTP server (for OpenAI agents or other HTTP clients)
MCP_TRANSPORT=http MCP_HOST=0.0.0.0 MCP_PORT=8000 uv run python -m redflag_mcp

# Start from a packaged corpus instead of LanceDB
REDFLAG_CORPUS_PACKAGE=dist/corpus/redflag-corpus-2026.04.29.zip uv run python -m redflag_mcp
```

The server exposes hosted-client-compatible tools for request routing, ranked relevance search, exact metadata filtering, source browsing, and filter discovery:

- `classify_red_flag_request` for deciding whether an ambiguous request needs more context, exact metadata filtering, filtered ranked relevance search, or direct ranked relevance search
- `search_red_flags` for natural-language relevance search with sourced, ranked results
- `filter_red_flags` for exact metadata requests that should not use ranked relevance search. Filters include `subjects`, `industry_groups`, `product_types`, `industry_types`, `customer_profiles`, `geographic_footprints`, `typology_family`, `transaction_patterns`, `category`, `risk_level`, `regulator`, `regulator_jurisdiction`, `issued_after`, `issued_before`, `regulatory_source`, `source_url`, and `source_id`. Exact filter responses include `total_matched`, `returned`, `truncated`, and `next_cursor` for complete pagination, plus `detail="concise"` for cheap enumeration before calling `get_red_flag`.
- `get_red_flag` for the full text and citation metadata for one red flag
- `list_filters` for available metadata filter values, including geography tokens such as `north_korea` when present in the active corpus
- `list_sources` and `get_source` for ingested source coverage and citation context

Successful `search_red_flags` and `filter_red_flags` responses include the raw `results` records plus presentation helpers for chat clients:

```json
{
  "results": [],
  "display": {
    "suggested_format": "table",
    "title": "Red flags for TBML invoice mismatch",
    "columns": [
      {"key": "description", "label": "Red flag"},
      {"key": "risk_level", "label": "Risk"},
      {"key": "transaction_patterns", "label": "Pattern"},
      {"key": "regulator", "label": "Regulator"},
      {"key": "source_url", "label": "Source"}
    ],
    "row_count": 0
  },
  "markdown_table": "| Red flag | Risk | Pattern | Regulator | Source |..."
}
```

`display` is a rendering hint for clients or models that choose to build a table UI from structured results. `markdown_table` is the portable fallback for ChatGPT, Claude, and other Markdown-capable clients; MCP does not guarantee a native table widget.

It is fully offline after ingestion or corpus installation — no API keys required at query time.

### Use from Codex

For local Codex threads, prefer stdio so Codex starts the MCP server automatically:

```bash
codex mcp add redflag-mcp -- zsh -lc 'cd /Users/learningmachine/Documents/Python-dev/redflag-mcp && HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 uv run python -m redflag_mcp'
```

Verify the registration:

```bash
codex mcp list
codex mcp get redflag-mcp
```

Then start a new Codex thread and ask for the server by name, for example:

```text
Use the redflag-mcp MCP server. List the available AML red flag filters.
```

If you already have the HTTP server running, you can register that instead:

```bash
codex mcp add redflag-mcp-http --url http://127.0.0.1:8000/mcp
```

### Local smoke checks

After ingesting the three target files, verify the tools with:

```text
list_filters
list_sources
classify_red_flag_request(query="what red flags apply to my crypto product?")
filter_red_flags(product_types=["depository"], category="fraud_nexus", risk_level="medium")
filter_red_flags(subjects=["human_trafficking"], regulator="FINTRAC")
filter_red_flags(industry_groups=["trade_logistics"])
filter_red_flags(typology_family=["trade_based_money_laundering"], transaction_patterns=["trade_document_manipulation"])
filter_red_flags(regulator="FinCEN", issued_after="2024", issued_before="2026")
filter_red_flags(regulator_jurisdiction="FR")
search_red_flags(query="federal child nutrition program sponsor receives reimbursements inconsistent with its profile", product_types=["depository"])
search_red_flags(query="TBML invoice mismatch")
search_red_flags(query="southwest border oil company wires for waste oil or hazardous materials")
search_red_flags(query="bulk cash moved by armored car service to Mexico")
get_red_flag(red_flag_id="001_federal_child_nutrition_fraud-01")
```

For a vague query such as "what should I look for in business accounts?", the calling agent should call `classify_red_flag_request` and ask a brief consultation question covering product/channel, industry, customer profile, geography, and transaction channel or volume when the route is `needs_more_context`. Skip the classifier when the user already gives specific metadata filters or a concrete scenario.

`category` is the primary classification of a record. `subjects` is a broader eligibility/tagging layer for investigative topics, and `typology_family` is a broader proceeds or typology grouping. For broad investigative topics such as "human trafficking red flags", use `subjects` instead of raw `category` so broader typology-family matches are included. For example, a trafficking-relevant darknet crypto flag may have `category="virtual_currency"` while still matching `subjects=["human_trafficking"]`.

`regulator_jurisdiction` describes the issuing regulator's jurisdiction. `geographic_footprints` describes the affected geography or typology geography. For exact metadata requests such as "show medium-risk fraud nexus red flags for depository products" or "red flags from regulators in France", call `filter_red_flags` instead of ranked search, translating country names to `regulator_jurisdiction` codes such as `FR`, `SG`, `AU`, `GB`, `US`, and `EU` when the request is about issuing regulators. For broad sector requests such as "trade logistics red flags", use `industry_groups`; keep raw `industry_types` for exact sector values such as `maritime_shipping`. If a `filter_red_flags` response has `truncated=true`, continue with `next_cursor` until `truncated=false` before presenting an exhaustive answer. `search_red_flags` is ranked and limit-based; request a higher limit for more ranked results rather than looking for a cursor. For requests with both usable filters and a rich narrative, call `search_red_flags` with filters so metadata controls eligibility while the query ranks the matching records.

---

## Development

```bash
uv sync --extra dev              # Install dev dependencies
uv sync --extra optimize         # Install DSPy for verifier optimization
uv run pytest tests/             # Run tests
uv run ruff check src/           # Lint
uv run mypy src/                 # Type check
```
