FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    UV_VERSION=0.8.4 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY src ./src

RUN python -m pip install --no-cache-dir "uv==${UV_VERSION}" \
    && uv sync --no-dev --frozen

COPY data ./data
COPY dist ./dist
COPY docs ./docs
COPY scripts ./scripts
COPY railway.toml ./

CMD ["sh", "-c", "uv run uvicorn redflag_mcp.http_app:app --host 0.0.0.0 --port ${PORT:-8000}"]
