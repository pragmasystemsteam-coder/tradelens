"""Dependency wiring for the API: the only place concrete infrastructure is chosen (ADR-0001)."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI

from tradelens.core.config import AppConfig
from tradelens.modules.analysis.public import SqlChartSource
from tradelens.modules.analysis.router import ChartSource, get_chart_source
from tradelens.modules.monitoring.router import get_checks, get_full_checks
from tradelens.modules.monitoring.service import (
    FullHealthChecks,
    HealthChecks,
    InfraHealthChecks,
)


def wire(app: FastAPI, config: AppConfig) -> None:
    """Bind module dependency placeholders to real implementations.

    Args:
        app: The application to wire.
        config: Configuration with database and Redis URLs.
    """
    checks = InfraHealthChecks(config.database_url, config.redis_url)

    def provide_checks() -> HealthChecks:
        return checks

    def provide_full_checks() -> FullHealthChecks:
        return checks

    app.dependency_overrides[get_checks] = provide_checks
    app.dependency_overrides[get_full_checks] = provide_full_checks
    if config.app_env != "development":
        return  # the dev chart routes are not mounted outside development
    chart = SqlChartSource(config.database_url, Path(os.environ.get("CONFIG_DIR", "config")))

    def provide_chart_source() -> ChartSource:
        return chart

    app.dependency_overrides[get_chart_source] = provide_chart_source
