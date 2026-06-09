---
date: 2026-06-06
topic: regulatory-source-monitoring-automation
---

# Regulatory Source Monitoring Automation

## Problem Frame

The red flag corpus depends on primary regulatory, law-enforcement, FIU, sanctions, and cyber-advisory sources. Today, new source discovery is mostly manual: a maintainer reviews official publication pages, copies URLs, downloads PDFs or web pages into `red_flag_sources/pdf/` and `red_flag_sources/markdown/`, then separately decides what to extract and ingest.

The project already has a URL-to-source pipeline and a unified `red_flag_sources/registry.csv`, but it does not yet have a recurring job that checks the official source inventory for newly published documents. A weekly Codex automation should reduce source coverage drift by checking prioritized primary sources every Saturday morning, downloading only new official files/pages, and leaving extraction and corpus updates as separate reviewable steps.

## Requirements

**Source Coverage**
- R1. The monitoring job uses the source lists in `red_flag_sources/regulatory_souce_automation.md` and the corresponding CSV files under `red_flag_sources/` as the source-tracking baseline.
- R2. The job prioritizes Tier 1 sources from `red_flag_sources/prioritization_ranking.csv`, then Tier 2, then Tier 3 when runtime or reliability constraints require a narrower pass.
- R3. The job monitors official primary-source publication endpoints, not third-party news, commentary, or scraped reposts.
- R4. Empty or incomplete tracking CSVs are treated as setup gaps to report, not silently ignored.

**Discovery And Download**
- R5. On each weekly run, the job checks tracked publication endpoints for newly published official documents or pages relevant to AML, sanctions, fraud, terrorist financing, proliferation financing, cyber-enabled financial crime, or related regulatory red flags.
- R6. A source is considered new only when its normalized URL is not already present in `red_flag_sources/registry.csv` or the source URL registry used by the download pipeline.
- R7. New PDFs are downloaded into `red_flag_sources/pdf/`; new web pages or non-PDF publication pages are saved into `red_flag_sources/markdown/`.
- R8. The job does not overwrite an existing local file unless explicitly run in a force or repair mode outside the normal Saturday automation.
- R9. The job records enough run output for a maintainer to see which endpoints were checked, which new URLs were found, which files were downloaded, which URLs were skipped as duplicates, and which checks failed.

**Reviewable Output**
- R10. The normal Saturday automation is download-only: it does not extract red flags, call LLM extraction, ingest into LanceDB, rebuild a corpus package, or publish a hosted update.
- R11. The job produces a concise summary suitable for a Codex automation result, including counts for endpoints checked, new URLs found, downloads completed, duplicates skipped, and failures.
- R12. Failed endpoint checks do not fail the entire run when other sources can still be checked; failures are surfaced in the summary with enough context for follow-up.
- R13. After successful downloads, the source registry is updated or regenerated so newly downloaded items are visible as `downloaded` sources for later extraction.

**Automation Behavior**
- R14. The recurring job runs every Saturday at 9:00 AM in the user's local timezone unless the maintainer changes the automation schedule.
- R15. The automation is safe to re-run manually after a failure without duplicating files or registry rows.
- R16. The automation should favor respectful polling and bounded work over exhaustive scraping when official endpoints are slow, blocked, or unstable.

## Success Criteria

- A Saturday run can check the tracked endpoint inventory without manual URL copying and correctly distinguish newly published official sources from no-change runs.
- When new eligible sources exist, the job downloads them into the correct local folder.
- Re-running the same job after a successful run reports the same URLs as duplicates or already tracked, with no duplicate local files.
- New downloaded sources appear in `red_flag_sources/registry.csv` with `downloaded` status or equivalent visibility for the existing extraction workflow.
- The automation result gives a maintainer a clear audit trail of what changed and what needs attention.
- Extraction and ingestion remain unchanged and can be run later using the existing pipeline.

## Scope Boundaries

- No automatic red flag extraction in the Saturday automation.
- No automatic LanceDB ingestion or hosted corpus publication.
- No automatic subscription to email lists or authenticated portals.
- No third-party news monitoring.
- No attempt to solve CAPTCHA-protected, paywalled, login-gated, or intentionally blocked sources in the normal automation.
- No manual curation decisions are made by the job beyond identifying official source URLs and downloading eligible new files/pages.

## Key Decisions

- **Separate requirements doc**: This feature is distinct from the unified registry because it defines recurring source monitoring behavior, while the registry remains the ledger of source status.
- **Download-only weekly automation**: New files should be reviewable before extraction, ingestion, or corpus publication. This keeps the recurring job lower-risk and limits LLM/API/model failure modes.
- **Registry-based deduplication**: `red_flag_sources/registry.csv` and the existing source URL registry are the authoritative basis for skipping already-known URLs.
- **Primary sources only**: The system should compound the corpus from official regulatory and law-enforcement material, not from secondary summaries.
- **Tiered monitoring**: Prioritization from `red_flag_sources/prioritization_ranking.csv` gives the job a graceful fallback when some endpoints are expensive, unreliable, or too broad.
- **Default schedule**: Saturday at 9:00 AM local time is specific enough for automation planning while preserving the user's requested Saturday morning cadence.

## Dependencies / Assumptions

- `scripts/pipeline.py` already supports downloading supplied URLs and updating source status; the monitoring job can hand newly discovered URLs to that workflow during implementation planning.
- `red_flag_sources/source_inventory.csv` and `red_flag_sources/subscription_automation.csv` currently exist but are empty; planning should decide whether to populate them from `red_flag_sources/regulatory_souce_automation.md` before implementation.
- Some source endpoints listed in `red_flag_sources/regulatory_souce_automation.md` may have changed since the document was created; planning should verify official endpoints before relying on them.
- The existing extraction workflow remains the downstream path for turning downloaded files into `data/source/*.yaml`.

## Outstanding Questions

### Deferred to Planning

- [Affects R1, R4][Technical] Should implementation first regenerate/populate the empty tracking CSVs from `red_flag_sources/regulatory_souce_automation.md`, or should it read the markdown document directly as the baseline?
- [Affects R5, R16][Needs research] Which tracked endpoints provide RSS/API/XML feeds that can be checked cheaply, and which require HTML page diffing?
- [Affects R7, R13][Technical] Should the monitoring job call `scripts/pipeline.py download` directly, import its functions, or produce a URL file for a separate pipeline step?
- [Affects R9, R11][Technical] What durable run artifact, if any, should supplement the Codex automation summary for auditability?

## Next Steps

-> `/ce:plan` for structured implementation planning
