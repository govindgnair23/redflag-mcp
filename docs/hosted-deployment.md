# Hosted Deployment

This document is for operators deploying the public hosted MCP connector. End users should only need the deployed connector URL, for example `https://<deployment>/mcp`.

Public hosted mode is not for confidential customer, transaction, institution, or investigation details. It is a convenience mode for public-source AML red flag research. Use local desktop or institution-hosted deployments when prompts include sensitive context.

## Runtime Shape

- MCP endpoint: `/mcp`
- Process liveness: `/health`
- Corpus readiness: `/ready`
- ASGI app: `redflag_mcp.http_app:app`
- First hosted mode: anonymous, single instance, process-local rate and concurrency limits

Railway should use `/ready` as the deployment healthcheck. `/health` only proves that HTTP is running; `/ready` proves that a verified corpus has activated. Railway healthcheck requests use host `healthcheck.railway.app`, so include that host in `REDFLAG_ALLOWED_HOSTS`.

## Corpus Artifact

Build the corpus before web-service deployment:

```bash
uv run python scripts/build_corpus.py \
  --output-dir dist/corpus \
  --version 2026.04.29 \
  --build-timestamp 2026-04-29T12:00:00Z \
  --all-sources
```

Verify the package and publish or package an external release index:

```bash
uv run python scripts/verify_corpus.py dist/corpus/redflag-corpus-2026.04.29.zip
```

The hosted runtime should activate from `REDFLAG_CORPUS_RELEASE_INDEX` plus `REDFLAG_CORPUS_VERSION`, or from `REDFLAG_CORPUS_PACKAGE` plus `REDFLAG_CORPUS_PACKAGE_SHA256`. Do not build from mutable source folders during web-service startup.

Original PDFs and source text stay under `red_flag_sources/` or controlled build storage. Approved extracted YAML lives under `data/source/`. Runtime serves the packaged `redflags.sqlite`, corpus manifest metadata, citation URLs, and bounded red flag snippets. It should not expose raw original documents unless source-level metadata explicitly clears redistribution.

## Railway

`railway.toml` configures:

- `uv sync --frozen` for dependency installation
- `uv run uvicorn redflag_mcp.http_app:app --host 0.0.0.0 --port $PORT` for startup
- `/ready` as the deployment healthcheck path
- hosted corpus runtime variables and public request bounds

Keep the first deployment to one service instance because the current rate limiter and concurrency cap are process-local.

Set or override these Railway variables for the deployment:

```text
REDFLAG_RUNTIME_MODE=hosted-corpus
REDFLAG_CORPUS_RELEASE_INDEX=dist/corpus/releases.json
REDFLAG_CORPUS_VERSION=2026.04.29
REDFLAG_CORPUS_CACHE_DIR=/app/.redflag-mcp
REDFLAG_ALLOWED_HOSTS=healthcheck.railway.app,<public-domain>,<custom-domain>
REDFLAG_ALLOWED_ORIGINS=<optional comma-separated browser origins>
REDFLAG_MAX_REQUEST_BYTES=1000000
REDFLAG_MAX_CONCURRENT_REQUESTS=10
REDFLAG_RATE_LIMIT_PER_MINUTE=120
```

Railway injects `$PORT`; do not hard-code the port in the start command. Railway's deployment healthcheck is an activation gate, not continuous uptime monitoring. Add external uptime monitoring if public availability becomes important.

## Logging And Privacy

Application code should log operational state only: startup, readiness failures, verification failures, and aggregate safety counters. It must not log MCP request bodies, user prompts, or tool arguments. Platform access logs may still record request path, status, source IP, user agent, and timing. Operator access to logs should be limited to maintainers responsible for the public service.

If a user accidentally submits sensitive details to the public hosted service, treat it as an operator incident: avoid copying the prompt into tickets or chat, remove retained application logs if present, and direct the user to local or institution-hosted deployment for sensitive work.

## Rollback

Rollback is anchored on the corpus artifact, not only on the Railway deployment. Pin a previous `REDFLAG_CORPUS_VERSION` in the release index or point `REDFLAG_CORPUS_PACKAGE` at a previously verified ZIP with its external checksum, then redeploy. Railway rollback or redeploy can help while the target deployment remains in Railway retention, but the corpus version/checksum remains the source of truth.

## Release Validation

Before public launch or corpus updates:

1. Build the corpus package with a deterministic timestamp.
2. Verify the package and external checksum or release index.
3. Run the hosted retrieval benchmark:
   ```bash
   uv run python scripts/evaluate_retrieval.py \
     --corpus dist/corpus/redflag-corpus-2026.04.29.zip \
     --benchmark data/eval/hosted_retrieval_queries.yaml
   ```
4. Deploy to Railway and confirm `/ready` returns corpus metadata.
5. Smoke-test `/mcp` in a target hosted client or MCP Inspector: anonymous URL accepted, tools visible, first query succeeds.

If a target hosted client rejects anonymous Streamable HTTP, treat the smallest auth fallback as a launch blocker or follow-up before public release.
