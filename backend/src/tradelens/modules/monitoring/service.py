"""Health checks for the API container (Detailed Design 4.8).

``/healthz`` checks only PostgreSQL and Redis, so a dead worker never restarts the API;
``/healthz/full`` (task 1.9) adds the worker heartbeat and data freshness.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from tradelens.core.db import get_engine
from tradelens.core.keys import HEARTBEAT_KEY, PRICE_STREAM_KEY
from tradelens.core.redis import create_redis
from tradelens.modules.monitoring import repository

logger = logging.getLogger(__name__)


class HealthChecks(Protocol):
    """Anything that can report whether the database and Redis answer."""

    def db_ok(self) -> bool:
        """Return True when the database answers SELECT 1."""
        ...

    def redis_ok(self) -> bool:
        """Return True when Redis answers PING."""
        ...


@dataclass(frozen=True, slots=True)
class HealthReport:
    """Result of one health check run."""

    db: bool
    redis: bool

    @property
    def ok(self) -> bool:
        """True when every dependency is healthy."""
        return self.db and self.redis


def run_checks(checks: HealthChecks) -> HealthReport:
    """Run every check once.

    Args:
        checks: The checks to run.

    Returns:
        The combined report.
    """
    return HealthReport(db=checks.db_ok(), redis=checks.redis_ok())


HEARTBEAT_MAX_AGE_S = 15.0  # heartbeat written every 5 s with a 15 s TTL (DD 4.8)
SERIES_MAX_AGE_S = 600.0  # an ingest pass runs every 5 minutes; two missed passes = unhealthy
PRICES_MAX_AGE_S = 15.0  # price ticks at least every 5 s (candle-close source, CR-004)


class FullHealthChecks(HealthChecks, Protocol):
    """Everything ``/healthz/full`` looks at; ages are seconds, None when never seen."""

    def heartbeat_age(self) -> float | None:
        """Age of the worker heartbeat."""
        ...

    def series_check_age(self) -> float | None:
        """Age of the newest ``series_status.last_checked_at`` (last ingest pass)."""
        ...

    def price_stream_age(self) -> float | None:
        """Age of the last price tick the worker handled."""
        ...


@dataclass(frozen=True, slots=True)
class FullReport:
    """Result of ``/healthz/full``."""

    db: bool
    redis: bool
    worker: bool
    series: bool
    prices: bool

    @property
    def ok(self) -> bool:
        """True when every check passed."""
        return self.db and self.redis and self.worker and self.series and self.prices


def _fresh(age: float | None, limit: float) -> bool:
    return age is not None and -limit <= age <= limit


def run_full_checks(checks: FullHealthChecks) -> FullReport:
    """Run ``/healthz/full``: infrastructure, worker heartbeat, ingest freshness, price stream.

    Used by UptimeRobot, not by Docker, so a dead worker never restarts the API (DD 4.8).
    """
    return FullReport(
        db=checks.db_ok(),
        redis=checks.redis_ok(),
        worker=_fresh(checks.heartbeat_age(), HEARTBEAT_MAX_AGE_S),
        series=_fresh(checks.series_check_age(), SERIES_MAX_AGE_S),
        prices=_fresh(checks.price_stream_age(), PRICES_MAX_AGE_S),
    )


class PingableRedis(Protocol):
    """The part of a Redis client the health check uses."""

    def ping(self) -> object:
        """Round-trip to the server."""
        ...

    def get(self, name: str) -> object:
        """Return the stored value or None."""
        ...

    def close(self) -> None:
        """Release the client's connections."""
        ...


class InfraHealthChecks:
    """Health checks against the real PostgreSQL and Redis (2 s budget each)."""

    def __init__(
        self,
        database_url: str,
        redis_url: str,
        redis_factory: Callable[[str], PingableRedis] = create_redis,
    ) -> None:
        """Store the connection URLs.

        Args:
            database_url: SQLAlchemy URL ("" counts as down).
            redis_url: Redis URL ("" counts as down).
            redis_factory: Builds a client per check; injected by tests.
        """
        self._database_url = database_url
        self._redis_url = redis_url
        self._redis_factory = redis_factory

    def db_ok(self) -> bool:
        """Return True when the database answers SELECT 1."""
        if not self._database_url:
            return False
        try:
            with get_engine(self._database_url).connect() as conn:
                conn.execute(text("SELECT 1"))
        except (SQLAlchemyError, OSError) as exc:
            logger.warning("health check: database unavailable (%s)", type(exc).__name__)
            return False
        return True

    def redis_ok(self) -> bool:
        """Return True when Redis answers PING."""
        try:
            client = self._redis_factory(self._redis_url)
        except ValueError as exc:
            logger.warning("health check: redis not configured (%s)", type(exc).__name__)
            return False
        try:
            return bool(client.ping())
        except (RedisError, OSError) as exc:
            logger.warning("health check: redis unavailable (%s)", type(exc).__name__)
            return False
        finally:
            client.close()  # one client per check; never leak sockets on Docker's polling

    def _redis_age(self, key: str) -> float | None:
        try:
            client = self._redis_factory(self._redis_url)
        except ValueError:
            return None
        try:
            raw = client.get(key)
            return None if raw is None else time.time() - float(str(raw))
        except (RedisError, OSError, ValueError) as exc:
            logger.warning("health check: %s unreadable (%s)", key, type(exc).__name__)
            return None
        finally:
            client.close()

    def heartbeat_age(self) -> float | None:
        """Age of the worker heartbeat in seconds."""
        return self._redis_age(HEARTBEAT_KEY)

    def price_stream_age(self) -> float | None:
        """Age of the last price tick in seconds."""
        return self._redis_age(PRICE_STREAM_KEY)

    def series_check_age(self) -> float | None:
        """Seconds since the newest ingest check of any series."""
        if not self._database_url:
            return None
        try:
            with get_engine(self._database_url).connect() as conn:
                return repository.last_check_age(conn)
        except (SQLAlchemyError, OSError) as exc:
            logger.warning("health check: series status unavailable (%s)", type(exc).__name__)
            return None
