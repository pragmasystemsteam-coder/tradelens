"""Health checks for the API container (Detailed Design 4.8).

``/healthz`` checks only PostgreSQL and Redis, so a dead worker never restarts the API;
``/healthz/full`` (task 1.9) adds the worker heartbeat and data freshness.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from tradelens.core.db import get_engine
from tradelens.core.redis import create_redis

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


class PingableRedis(Protocol):
    """The part of a Redis client the health check uses."""

    def ping(self) -> object:
        """Round-trip to the server."""
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
