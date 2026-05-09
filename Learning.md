# Learning: Hosted redflag-mcp Deployment

This note explains what was built, how the Railway deployment works, and the main design decisions behind the MCP server.

## What We Built

`redflag-mcp` is an MCP server for AML red flag research. A user asks questions like "What red flags apply to TBML invoice mismatch?" and the server returns sourced red flags from a packaged corpus.

The important shift was from a local developer workflow to a hosted URL workflow:

```text
https://redflag-mcp.up.railway.app/mcp
```

That URL is what a hosted MCP client, such as Claude Desktop, should connect to. The user should not need Python, a local database, OpenAI keys, or a manual ingestion step.

## The Three Public Endpoints

The hosted service exposes three important paths:

```text
/health
/ready
/mcp
```

`/health` is a simple liveness check. It returns HTTP 200 when the web process is running. Railway uses this as the deployment healthcheck.

`/ready` is the corpus readiness check. It returns corpus metadata when the verified corpus package loaded successfully. If this fails, the server is running but not usable for MCP queries.

`/mcp` is the actual MCP endpoint. This is the URL Claude Desktop or another MCP client should use.

## How Railway Deployment Works

Railway watches the GitHub repository. When `main` is pushed, Railway builds and deploys the service.

The deployment is controlled by two files:

```text
railway.toml
Dockerfile
```

`railway.toml` tells Railway to use the Dockerfile builder and to check `/health` after deployment:

```toml
[build]
builder = "DOCKERFILE"
dockerfilePath = "Dockerfile"

[deploy]
healthcheckPath = "/health"
```

The Dockerfile defines how to build and start the app. The key startup line is:

```dockerfile
CMD ["sh", "-c", "uv run uvicorn redflag_mcp.http_app:app --host 0.0.0.0 --port ${PORT:-8000}"]
```

Railway provides the `PORT` value. The `sh -c` wrapper matters because it lets `${PORT:-8000}` expand to the real Railway port.

## Problems We Hit On Railway

First, Railway generated a bad build command:

```text
pip install uv==
```

That failed because the uv version was blank. The fix was to stop using Railway's generated Python/Nixpacks build and add our own Dockerfile that pins uv:

```dockerfile
ENV UV_VERSION=0.8.4
RUN python -m pip install --no-cache-dir "uv==${UV_VERSION}" \
    && uv sync --no-dev --frozen
```

Second, Railway's `startCommand` used `$PORT`, but Dockerfile-style deployments did not expand it the way we expected. Uvicorn received the literal string `$PORT` and crashed. The fix was to remove `startCommand` from `railway.toml` and let the Dockerfile `CMD` start the app.

Third, `/ready` was too strict for Railway's deployment healthcheck. `/ready` returns 503 if the corpus is not activated. That is useful for operators, but it can prevent the container from becoming reachable for debugging. The fix was to use `/health` for Railway and keep `/ready` as the human/operator readiness check.

Fourth, `/mcp` returned:

```text
Invalid Host header
```

The MCP SDK has its own host-header security check. It defaulted to localhost-only. We patched the app so FastMCP uses the same allowed-host configuration as the hosted app. If allowed hosts are not configured, the SDK's localhost-only protection is disabled for this hosted deployment.

## The Corpus Artifact

The corpus is the actual AML red flag knowledge package. It is checked into the repo under:

```text
dist/corpus/redflag-corpus-2026.04.29.zip
dist/corpus/releases.json
```

The ZIP contains:

```text
manifest.json
redflags.sqlite
```

`redflags.sqlite` is a SQLite database using FTS5, SQLite's built-in full-text search engine. `manifest.json` records version, schema, hashes, source counts, and other provenance metadata.

`releases.json` tells the app which corpus package is available and what SHA-256 checksum it should have.

The hosted runtime defaults to:

```text
dist/corpus/releases.json
```

That means Railway can run even if the corpus environment variables are missing.

## Why SQLite FTS Instead Of Embeddings

The hosted mode intentionally does not use query-time embeddings, LanceDB, OpenAI, or a local embedding model.

Reasons:

- It avoids external calls when a user asks a question.
- It starts faster and is easier to host.
- It is deterministic: the same corpus and query produce predictable results.
- It is cheaper for a public demo endpoint.
- It avoids sending user queries to an embedding API.

The tradeoff is that lexical search can be less flexible than semantic search. To improve recall, the corpus includes aliases and enriched metadata such as:

```text
TBML -> trade based money laundering
CVC -> convertible virtual currency
product types
typology families
transaction patterns
key terms
source metadata
```

## Why There Are Two Runtime Modes

The project supports more than one runtime mode:

```text
hosted-corpus
local-corpus
vector-dev
```

`hosted-corpus` is the public hosted mode. It must load a verified corpus package. If it cannot, `/ready` fails and `/mcp` refuses traffic.

`local-corpus` is for running from a local SQLite corpus file or package.

`vector-dev` is the older developer mode that uses LanceDB and embeddings. This is useful for local experimentation but not for the hosted public deployment.

The key production rule is: hosted mode should fail closed. It should not silently fall back to vector search or embeddings.

## How Requests Flow Through The App

At a high level:

```text
Claude Desktop
  -> https://redflag-mcp.up.railway.app/mcp
  -> Railway
  -> Docker container
  -> Starlette ASGI app
  -> FastMCP
  -> redflag tools
  -> SQLite corpus
  -> sourced red flag results
```

The ASGI app lives in:

```text
src/redflag_mcp/http_app.py
```

The MCP server setup lives in:

```text
src/redflag_mcp/server.py
```

The tool behavior lives in:

```text
src/redflag_mcp/tools.py
```

The SQLite lexical search layer lives in:

```text
src/redflag_mcp/lexicalstore.py
```

## Public Safety Guardrails

The public endpoint is anonymous, so it has basic guardrails:

- maximum request body size
- allowed host handling
- optional allowed origins
- process-local rate limiting
- process-local concurrency cap
- maximum query length
- maximum filter cardinality

These are deliberately simple because the first deployment is one Railway service instance. If the service grows to multiple instances, rate limiting would need a shared store.

## Source Documents And Privacy

The hosted service is for public-source AML red flag research. It is not for confidential customer or investigation details.

Original PDFs and raw source documents are build inputs. The public runtime serves:

- citation URLs
- source metadata
- red flag snippets and descriptions
- corpus metadata

It should not serve raw original PDFs unless redistribution has been reviewed and approved.

## How To Check The Deployment

Use these commands:

```bash
curl https://redflag-mcp.up.railway.app/health
curl https://redflag-mcp.up.railway.app/ready
```

Expected:

```text
/health -> {"status":"ok"}
/ready  -> {"status":"ready", "corpus": ...}
```

To test the MCP endpoint manually:

```bash
curl -i https://redflag-mcp.up.railway.app/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"1.0"}}}'
```

If this returns `Invalid Host header`, the deployed version is old or the host configuration is wrong.

## How To Connect Claude Desktop

Use the HTTPS MCP URL:

```text
https://redflag-mcp.up.railway.app/mcp
```

Do not use:

```text
http://...
https://redflag-mcp.up.railway.app
https://redflag-mcp.up.railway.app/ready
```

Claude needs the MCP endpoint, which is `/mcp`.

## How To Update The Corpus Later

The basic process is:

1. Update or add approved YAML source records under `data/source/`.
2. Rebuild the corpus package:

   ```bash
   uv run python scripts/build_corpus.py \
     --output-dir dist/corpus \
     --version <new-version> \
     --build-timestamp <timestamp> \
     --all-sources
   ```

3. Update `dist/corpus/releases.json`.
4. Verify the corpus package:

   ```bash
   uv run python scripts/verify_corpus.py dist/corpus/redflag-corpus-<new-version>.zip
   ```

5. Run the retrieval benchmark:

   ```bash
   uv run python scripts/evaluate_retrieval.py \
     --corpus dist/corpus/redflag-corpus-<new-version>.zip \
     --benchmark data/eval/hosted_retrieval_queries.yaml
   ```

6. Commit and push to GitHub.
7. Railway redeploys from `main`.

## Key Architecture Decisions

Use MCP tools as the product interface. The server exposes read-only tools for search, filtering, red flag lookup, source browsing, and filter discovery.

Keep hosted mode offline at query time. The hosted server should not call OpenAI, download embedding models, or query an external vector database when answering a user.

Use a packaged corpus as the release artifact. The corpus ZIP is versioned, hashed, inspectable, and rollback-friendly.

Use `/health` and `/ready` separately. `/health` answers "is the web process alive?" `/ready` answers "is the verified corpus active?"

Fail closed in hosted mode. If the verified corpus is missing or invalid, MCP traffic should not fall back to vector mode.

Keep public hosted mode distinct from private modes. Public hosted mode optimizes ease of setup. Local and institution-hosted modes are the better fit for sensitive prompts.

Prefer deterministic lexical retrieval for the first hosted milestone. It is simpler, cheaper, inspectable, and avoids external query-time dependencies.

Document operator responsibilities. The easy user experience depends on the operator owning corpus builds, release checks, Railway config, hostnames, logs, and rollback.

## Most Important Lesson

Getting the hosted MCP URL working was not only about the Python code. The deployment depended on several layers agreeing with each other:

```text
GitHub files
Railway build settings
Dockerfile startup command
Railway healthcheck path
Railway hostname
FastMCP transport security
Corpus release index
Claude Desktop MCP URL
```

When one layer was wrong, the service could look partly healthy but still fail in Claude Desktop. The final design makes those layers explicit and testable.
