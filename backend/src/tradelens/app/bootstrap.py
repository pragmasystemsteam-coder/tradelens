"""Dependency wiring for the API: the only place concrete infrastructure is chosen (ADR-0001)."""

from __future__ import annotations

from fastapi import FastAPI

from tradelens.core.config import AppConfig
from tradelens.modules.monitoring.router import get_checks
from tradelens.modules.monitoring.service import HealthChecks, InfraHealthChecks


def wire(app: FastAPI, config: AppConfig) -> None:
    """Bind module dependency placeholders to real implementations.

    Args:
        app: The application to wire.
        config: Configuration with database and Redis URLs.
    """
    checks = InfraHealthChecks(config.database_url, config.redis_url)

    def provide_checks() -> HealthChecks:
        return checks

    app.dependency_overrides[get_checks] = provide_checks
