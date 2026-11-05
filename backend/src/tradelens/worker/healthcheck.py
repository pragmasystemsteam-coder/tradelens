"""Docker health check for the worker: ``python -m tradelens.worker.healthcheck``.

Exit 0 when the heartbeat is younger than HEARTBEAT_TTL_SECONDS, else 1 (Detailed Design 4.8).
"""

from __future__ import annotations

import sys
import time
from typing import Protocol

from redis.exceptions import RedisError

from tradelens.core.config import AppConfig
from tradelens.core.redis import create_redis
from tradelens.worker.heartbeat import HEARTBEAT_KEY

HEALTHY, UNHEALTHY = 0, 1


class HeartbeatSource(Protocol):
    """The part of a Redis client the health check needs."""

    def get(self, name: str) -> object:
        """Return the stored value or None."""
        ...


def check(redis: HeartbeatSource, now: float, ttl: int) -> int:
    """Decide whether the worker is alive.

    A heartbeat further in the future than ``ttl`` (clock skew) also counts as unhealthy.

    Args:
        redis: Redis client.
        now: Current Unix time in seconds.
        ttl: Maximum heartbeat age in seconds.

    Returns:
        0 when healthy, 1 otherwise (Docker health check exit codes).
    """
    try:
        raw = redis.get(HEARTBEAT_KEY)
    except (RedisError, OSError):
        return UNHEALTHY
    if raw is None:
        return UNHEALTHY
    try:
        last = float(str(raw))
    except ValueError:
        return UNHEALTHY
    return HEALTHY if abs(now - last) <= ttl else UNHEALTHY


def main() -> int:
    """Run the check against REDIS_URL.

    Returns:
        The process exit code.
    """
    config = AppConfig.from_env()
    try:
        redis = create_redis(config.redis_url)
    except ValueError:
        return UNHEALTHY
    return check(redis, time.time(), config.heartbeat_ttl_seconds)


if __name__ == "__main__":
    sys.exit(main())
