"""HTTP routes for health checks (Detailed Design 4.8). Thin: logic lives in service.py."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from tradelens.modules.monitoring.service import (
    FullHealthChecks,
    HealthChecks,
    run_checks,
    run_full_checks,
)

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


def get_full_checks() -> FullHealthChecks:
    """Dependency placeholder for ``/healthz/full``; wired in ``tradelens.app.bootstrap``.

    Raises:
        RuntimeError: Always, if the app was built without wiring.
    """
    raise RuntimeError("monitoring checks are not wired; build the app with create_app()")


@router.get("/healthz/full")
def healthz_full(checks: Annotated[FullHealthChecks, Depends(get_full_checks)]) -> JSONResponse:
    """Uptime check: 200 when the worker, data and prices are fresh as well, else 503."""
    report = run_full_checks(checks)
    body = {
        "status": "ok" if report.ok else "error",
        "checks": {"db": report.db, "redis": report.redis, "worker": report.worker,
                   "series": report.series, "prices": report.prices},
    }  # fmt: skip
    code = status.HTTP_200_OK if report.ok else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(body, status_code=code)
