"""FastAPI application factory.

Run with ``uvicorn tradelens.app.main:create_app --factory`` (ADR-0001).
"""

from __future__ import annotations

from fastapi import FastAPI

from tradelens.app.bootstrap import wire
from tradelens.app.middleware import RequestIdMiddleware
from tradelens.app.routers import DEV_ROUTERS, ROUTERS
from tradelens.core.config import AppConfig

API_TITLE = "TradeLens API"
API_VERSION = "0.1.0"
PRODUCTION = "production"
DEVELOPMENT = "development"


def create_app(config: AppConfig | None = None) -> FastAPI:
    """Build the API application.

    API docs are served only when ENABLE_API_DOCS is true (never in production, section 6.1).

    Args:
        config: Configuration to use; read from the environment when None.

    Returns:
        The configured application.

    Raises:
        RuntimeError: If API docs are enabled in production.
    """
    cfg = config or AppConfig.from_env()
    if cfg.app_env == PRODUCTION and cfg.enable_api_docs:
        raise RuntimeError("ENABLE_API_DOCS must be false in production (Detailed Design 6.1)")
    app = FastAPI(
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
    app.add_middleware(RequestIdMiddleware)
    wire(app, cfg)
    return app
