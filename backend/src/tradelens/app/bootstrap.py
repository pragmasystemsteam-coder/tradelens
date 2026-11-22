"""Dependency wiring for the API: the only place concrete infrastructure is chosen (ADR-0001).

``Infra`` holds the database engine, Redis clients and clock; ``wire`` binds every
``core.deps`` placeholder to them. Tests pass their own ``Infra`` (throwaway PostgreSQL, fake
Redis, frozen clock).
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Request, Response
from sqlalchemy import Connection, Engine

from tradelens.app.security import viewer
from tradelens.core import deps
from tradelens.core.config import AppConfig
from tradelens.core.errors import not_authenticated
from tradelens.modules.analysis.public import SqlChartSource
from tradelens.modules.analysis.router import ChartSource, get_chart_source
from tradelens.modules.billing.public import (
    account_summary,
    end_subscriptions,
    entitlements,
    invalidate_entitlements,
    paid_subscription_live,
    start_trial,
)
from tradelens.modules.market_data.public import instrument_rows
from tradelens.modules.monitoring.router import get_checks, get_full_checks
from tradelens.modules.monitoring.service import (
    FullHealthChecks,
    HealthChecks,
    InfraHealthChecks,
)

# Sync routes run on AnyIO worker threads, and every step of a request (dependencies, then the
# route) takes a thread again. With fewer connections than threads, all threads can block
# waiting for a connection while the holders wait for a thread: a deadlock until the 30 s pool
# timeout (seen at 100 concurrent /setups). So the thread limit equals the pool capacity.
DB_POOL_SIZE = 10
DB_POOL_OVERFLOW = 30
API_THREADS = DB_POOL_SIZE + DB_POOL_OVERFLOW


_db_slots: dict[int, asyncio.Semaphore] = {}


async def db_slot() -> AsyncIterator[None]:
    """At most ``API_THREADS`` requests may hold or wait for a pooled connection at once.

    The wait happens here, on the event loop, so a worker thread never blocks inside the pool
    while the connection holders wait for a free thread (the deadlock the load check found
    with 100 concurrent requests). One semaphore per event loop (tests start several).
    """
    loop = id(asyncio.get_running_loop())
    sem = _db_slots.get(loop)
    if sem is None:
        sem = _db_slots[loop] = asyncio.Semaphore(API_THREADS)
    async with sem:
        yield


ACCOUNT_BILLING = deps.AccountBilling(
    start_trial=start_trial,
    paid_subscription_live=paid_subscription_live,
    end_subscriptions=end_subscriptions,
    forget_entitlements=invalidate_entitlements,
)


def utc_now() -> datetime:
    """The production clock."""
    return datetime.now(UTC)


@dataclass(slots=True)
class Infra:
    """Concrete infrastructure of one API process."""

    engine: Engine | None
    redis: Any  # redis.Redis (decode_responses=True)
    async_redis: Any  # redis.asyncio.Redis
    clock: Callable[[], datetime] = utc_now


def build_infra(config: AppConfig) -> Infra:
    """Production infrastructure from the configuration (lazy connections)."""
    from redis import asyncio as aioredis

    from tradelens.core.db import get_engine
    from tradelens.core.redis import SOCKET_TIMEOUT_SECONDS, create_redis

    engine = (get_engine(config.database_url, pool_size=DB_POOL_SIZE, max_overflow=DB_POOL_OVERFLOW)
              if config.database_url else None)  # fmt: skip
    redis = create_redis(config.redis_url) if config.redis_url else None
    async_redis = (
        aioredis.from_url(config.redis_url, decode_responses=True,
                          socket_connect_timeout=SOCKET_TIMEOUT_SECONDS)
        if config.redis_url else None
    )  # fmt: skip
    return Infra(engine, redis, async_redis)


def wire(app: FastAPI, config: AppConfig, infra: Infra) -> None:
    """Bind module dependency placeholders to real implementations.

    Args:
        app: The application to wire.
        config: Configuration with database and Redis URLs and the API settings.
        infra: Engine, Redis clients and clock to use.
    """
    checks = InfraHealthChecks(config.database_url, config.redis_url)

    def provide_checks() -> HealthChecks:
        return checks

    def provide_full_checks() -> FullHealthChecks:
        return checks

    def provide_conn(
        _slot: Annotated[None, Depends(db_slot, scope="function")],
    ) -> Iterator[Connection | None]:
        if infra.engine is None:  # unit tests without a database
            yield None
            return
        with infra.engine.begin() as conn:
            yield conn

    def provide_summary() -> deps.AccountSummary:
        def summary(conn: Connection, user_id: str) -> Mapping[str, Any]:
            return account_summary(conn, user_id, entitlements(conn, user_id, infra.clock()))

        return summary

    def provide_stream_viewer(
        _slot: Annotated[None, Depends(db_slot, scope="function")],
        request: Request,
        redis: Annotated[Any, Depends(deps.get_redis)],  # noqa: ANN401 - redis.Redis
        cfg: Annotated[AppConfig, Depends(deps.get_config)],
        clock: Annotated[Callable[[], datetime], Depends(deps.get_clock)],
    ) -> deps.Viewer:
        """The viewer from a short transaction: a stream never holds a database connection."""
        if infra.engine is None:
            raise not_authenticated()
        with infra.engine.begin() as conn:
            return viewer(request, Response(), conn, redis, cfg, clock)

    classes: dict[str, str] = {}

    def provide_instrument_classes(
        _slot: Annotated[None, Depends(db_slot, scope="function")],
    ) -> Mapping[str, str]:
        if not classes and infra.engine is not None:
            with infra.engine.connect() as conn:
                classes.update({r["code"]: r["asset_class"] for r in instrument_rows(conn)})
        return classes

    overrides: dict[Callable[..., Any], Callable[..., Any]] = {
        get_checks: provide_checks,
        get_full_checks: provide_full_checks,
        deps.get_config: lambda: config,
        deps.get_clock: lambda: infra.clock,
        deps.get_redis: lambda: infra.redis,
        deps.get_async_redis: lambda: infra.async_redis,
        deps.get_conn: provide_conn,
        deps.get_viewer: viewer,
        deps.get_account_summary: provide_summary,
        deps.get_account_billing: lambda: ACCOUNT_BILLING,
        deps.get_stream_viewer: provide_stream_viewer,
        deps.get_instrument_classes: provide_instrument_classes,
    }
    app.dependency_overrides.update(overrides)
    if config.app_env != "development":
        return  # the dev chart routes are not mounted outside development
    chart = SqlChartSource(config.database_url, Path(os.environ.get("CONFIG_DIR", "config")))

    def provide_chart_source() -> ChartSource:
        return chart

    app.dependency_overrides[get_chart_source] = provide_chart_source
