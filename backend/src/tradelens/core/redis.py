"""Redis client factory (Redis 7: cache, rate limits, heartbeat, pub/sub)."""

from __future__ import annotations

from redis import Redis

SOCKET_TIMEOUT_SECONDS = 2.0  # same 2 s budget as the database health check


def create_redis(url: str, timeout_seconds: float = SOCKET_TIMEOUT_SECONDS) -> Redis:
    """Create a Redis client that returns str values.

    Args:
        url: Redis URL, e.g. redis://:password@redis:6379/0.
        timeout_seconds: Connect and socket timeout.

    Returns:
        A lazily connecting client.

    Raises:
        ValueError: If the URL is empty or malformed.
    """
    if not url:
        raise ValueError("REDIS_URL is empty")
    return Redis.from_url(
        url,
        socket_connect_timeout=timeout_seconds,
        socket_timeout=timeout_seconds,
        decode_responses=True,
    )
