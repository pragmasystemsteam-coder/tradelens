"""Worker heartbeat in Redis (Detailed Design 4.8: written every 5 s with a 15 s TTL)."""

from __future__ import annotations

from typing import Protocol

HEARTBEAT_KEY = "worker:heartbeat"


class HeartbeatStore(Protocol):
    """The part of a Redis client the heartbeat writer needs."""

    def set(self, name: str, value: str, ex: int | None = None) -> object:
        """Store ``value`` under ``name`` with an optional TTL in seconds."""
        ...


def beat(redis: HeartbeatStore, now: float, ttl: int) -> None:
    """Write the heartbeat.

    Args:
        redis: Redis client.
        now: Current Unix time in seconds (passed in so tests control the clock).
        ttl: Key lifetime in seconds; the key vanishes if the worker stops.
    """
    redis.set(HEARTBEAT_KEY, str(now), ex=ttl)
