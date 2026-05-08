from __future__ import annotations

import os
import time
from collections.abc import AsyncIterator, Mapping
from contextlib import AsyncExitStack, asynccontextmanager

from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route

from redflag_mcp.embeddings import EmbeddingModel
from redflag_mcp.server import (
    ReadinessState,
    RuntimeConfig,
    RuntimeMode,
    ServerState,
    build_server_state,
    create_server,
    load_runtime_config,
)


def create_http_app(
    *,
    runtime_config: RuntimeConfig | None = None,
    env: Mapping[str, str] | None = None,
    embedding_model: EmbeddingModel | None = None,
) -> Starlette:
    config = runtime_config or _load_hosted_runtime_config(env)
    guardrails = PublicHttpGuardrails.from_env(os.environ if env is None else env)
    readiness = ReadinessState.not_ready("Corpus activation has not run.")
    state_holder: dict[str, ServerState] = {}

    mcp = create_server(
        runtime_config=config,
        embedding_model=embedding_model,
        json_response=True,
        stateless_http=True,
        state_factory=lambda: state_holder["state"],
    )
    mcp_app = mcp.streamable_http_app()

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        state = build_server_state(config, embedding_model=embedding_model)
        state_holder["state"] = state
        app.state.server_state = state
        async with AsyncExitStack() as stack:
            await stack.enter_async_context(mcp_app.router.lifespan_context(mcp_app))
            yield

    async def health(_request: Request) -> Response:
        return JSONResponse({"status": "ok"})

    async def ready(request: Request) -> Response:
        state = getattr(request.app.state, "server_state", None)
        current = state.readiness if state is not None else readiness
        if current.ready:
            return JSONResponse({"status": "ready", "corpus": current.corpus})
        return JSONResponse(
            {"status": "not_ready", "message": current.message},
            status_code=503,
        )
    app = Starlette(
        routes=[
            Route("/health", health, methods=["GET"]),
            Route("/ready", ready, methods=["GET"]),
            Mount("/", app=mcp_app),
        ],
        lifespan=lifespan,
    )
    app.state.runtime_config = config
    app.state.guardrails = guardrails
    app.add_middleware(HostedReadinessMiddleware)
    app.add_middleware(PublicHttpGuardrailMiddleware)
    return app


class PublicHttpGuardrails:
    def __init__(
        self,
        *,
        max_request_bytes: int = 1_000_000,
        allowed_origins: set[str] | None = None,
        allowed_hosts: set[str] | None = None,
        rate_limit_per_minute: int = 120,
        max_concurrent_requests: int = 10,
    ) -> None:
        self.max_request_bytes = max_request_bytes
        self.allowed_origins = allowed_origins or set()
        self.allowed_hosts = allowed_hosts or set()
        self.rate_limit_per_minute = rate_limit_per_minute
        self.max_concurrent_requests = max_concurrent_requests
        self.active_requests = 0
        self.request_times: dict[str, list[float]] = {}

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> PublicHttpGuardrails:
        return cls(
            max_request_bytes=int(env.get("REDFLAG_MAX_REQUEST_BYTES", "1000000")),
            allowed_origins=_csv_set(env.get("REDFLAG_ALLOWED_ORIGINS")),
            allowed_hosts=_csv_set(env.get("REDFLAG_ALLOWED_HOSTS")),
            rate_limit_per_minute=int(env.get("REDFLAG_RATE_LIMIT_PER_MINUTE", "120")),
            max_concurrent_requests=int(
                env.get("REDFLAG_MAX_CONCURRENT_REQUESTS", "10")
            ),
        )

    def check_rate_limit(self, client_id: str, *, now: float | None = None) -> bool:
        if self.rate_limit_per_minute <= 0:
            return True
        now = now or time.monotonic()
        window_start = now - 60
        recent = [
            timestamp
            for timestamp in self.request_times.get(client_id, [])
            if timestamp >= window_start
        ]
        if len(recent) >= self.rate_limit_per_minute:
            self.request_times[client_id] = recent
            return False
        recent.append(now)
        self.request_times[client_id] = recent
        return True


class PublicHttpGuardrailMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        guardrails = getattr(request.app.state, "guardrails", PublicHttpGuardrails())

        host = request.headers.get("host", "").split(":", 1)[0]
        if guardrails.allowed_hosts and host not in guardrails.allowed_hosts:
            return _guardrail_error("host_not_allowed", 403)

        origin = request.headers.get("origin")
        if origin and guardrails.allowed_origins and origin not in guardrails.allowed_origins:
            return _guardrail_error("origin_not_allowed", 403)

        content_length = request.headers.get("content-length")
        if (
            content_length is not None
            and int(content_length) > guardrails.max_request_bytes
        ):
            return _guardrail_error("request_too_large", 413)

        client = request.client.host if request.client else "unknown"
        if not guardrails.check_rate_limit(client):
            return _guardrail_error("rate_limit_exceeded", 429)

        if guardrails.active_requests >= guardrails.max_concurrent_requests:
            return _guardrail_error("too_many_concurrent_requests", 503)

        guardrails.active_requests += 1
        try:
            return await call_next(request)
        finally:
            guardrails.active_requests -= 1


class HostedReadinessMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/mcp" or request.url.path.startswith("/mcp/"):
            runtime_config = getattr(request.app.state, "runtime_config", None)
            server_state = getattr(request.app.state, "server_state", None)
            if (
                runtime_config is not None
                and runtime_config.mode == RuntimeMode.HOSTED_CORPUS
                and (server_state is None or not server_state.readiness.ready)
            ):
                message = (
                    server_state.readiness.message
                    if server_state is not None
                    else "Corpus activation has not run."
                )
                return JSONResponse(
                    {"status": "not_ready", "message": message},
                    status_code=503,
                )
        return await call_next(request)


def _load_hosted_runtime_config(env: Mapping[str, str] | None) -> RuntimeConfig:
    values = dict(os.environ if env is None else env)
    values.setdefault("REDFLAG_RUNTIME_MODE", RuntimeMode.HOSTED_CORPUS.value)
    values.setdefault("REDFLAG_CORPUS_RELEASE_INDEX", "dist/corpus/releases.json")
    return load_runtime_config(values)


def _csv_set(value: str | None) -> set[str]:
    if not value:
        return set()
    return {item.strip() for item in value.split(",") if item.strip()}


def _guardrail_error(error: str, status_code: int) -> JSONResponse:
    return JSONResponse({"error": error}, status_code=status_code)


app = create_http_app()
