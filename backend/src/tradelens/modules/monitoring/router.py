"""HTTP routes for health checks (Detailed Design 4.8). Thin: logic lives in service.py."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from tradelens.modules.monitoring.service import HealthChecks, run_checks

router = APIRouter(tags=["monitoring"])


def get_checks() -> HealthChecks:
    """Dependency placeholder; ``tradelens.app.bootstrap.wire`` supplies the real checks.

    Raises:
        RuntimeError: Always, if the app was built without wiring.
    """
    raise RuntimeError("monitoring checks are not wired; build the app with create_app()")


@router.get("/healthz")
def healthz(checks: Annotated[HealthChecks, Depends(get_checks)]) -> JSONResponse:
    """Liveness for Docker: 200 when PostgreSQL and Redis answer, else 503 with details."""
    report = run_checks(checks)
    if report.ok:
        return JSONResponse({"status": "ok"})
    return JSONResponse(
        {"status": "error", "db": report.db, "redis": report.redis},
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    )
