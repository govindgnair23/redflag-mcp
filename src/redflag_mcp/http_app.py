from __future__ import annotations

import os
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
    app.add_middleware(HostedReadinessMiddleware)
    return app


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
    return load_runtime_config(values)


app = create_http_app()
