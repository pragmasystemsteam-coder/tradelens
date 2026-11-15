"""FastAPI application factory.

Run with ``uvicorn tradelens.app.main:create_app --factory`` (ADR-0001).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import anyio.to_thread
from fastapi import FastAPI

from tradelens.app import exception_handlers
from tradelens.app.bootstrap import API_THREADS, Infra, build_infra, wire
from tradelens.app.middleware import RequestIdMiddleware
from tradelens.app.routers import DEV_ROUTERS, ROUTERS
from tradelens.core.config import AppConfig

API_TITLE = "TradeLens API"
API_VERSION = "0.2.0"
PRODUCTION = "production"
DEVELOPMENT = "development"
WEAK_SECRETS = frozenset({"", "change-me"})
MIN_SECRET_LEN = 32
NO_SECRET_ENVS = frozenset({DEVELOPMENT, "test"})


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Never more worker threads than database connections (see ``bootstrap.API_THREADS``)."""
    limiter = anyio.to_thread.current_default_thread_limiter()
    limiter.total_tokens = API_THREADS
    app.state.thread_tokens = limiter.total_tokens
    yield


def _strong_secrets(cfg: AppConfig) -> bool:
    secrets = (cfg.session_secret, cfg.csrf_secret)
    return (all(s not in WEAK_SECRETS and len(s) >= MIN_SECRET_LEN for s in secrets)
            and cfg.session_secret != cfg.csrf_secret)  # fmt: skip


def create_app(config: AppConfig | None = None, *, infra: Infra | None = None) -> FastAPI:
    """Build the API application.

    API docs are served only when ENABLE_API_DOCS is true (never in production, section 6.1).

    Args:
        config: Configuration to use; read from the environment when None.
        infra: Database engine, Redis clients and clock (built from ``config`` when None).

    Returns:
        The configured application.

    Raises:
        RuntimeError: If API docs are enabled in production, or outside development and
            tests a session or CSRF secret is missing, shorter than 32 characters or shared.
    """
    cfg = config or AppConfig.from_env()
    if cfg.app_env == PRODUCTION and cfg.enable_api_docs:
        raise RuntimeError("ENABLE_API_DOCS must be false in production (Detailed Design 6.1)")
    if cfg.app_env not in NO_SECRET_ENVS and not _strong_secrets(cfg):
        raise RuntimeError(
            "SESSION_SECRET and CSRF_SECRET must be set, at least 32 characters and different"
            " (Detailed Design 6.1)"
        )
    app = FastAPI(
        lifespan=_lifespan,
        title=API_TITLE,
        version=API_VERSION,
        docs_url="/docs" if cfg.enable_api_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if cfg.enable_api_docs else None,
    )
    for router in ROUTERS:
        app.include_router(router)
    if cfg.app_env == DEVELOPMENT:
        for router in DEV_ROUTERS:
            app.include_router(router)
    exception_handlers.install(app)
    app.add_middleware(RequestIdMiddleware)
    wire(app, cfg, infra or build_infra(cfg))
    return app
