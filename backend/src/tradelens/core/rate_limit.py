"""Fixed-window rate limits in Redis (DD 4.1: sign-in, API, custom charts, anonymous posts).

``INCR`` a per-window counter and set its TTL on the first hit; over the limit the caller gets
the seconds left in the window for ``Retry-After``. Redis being down never blocks a request:
the limiter fails open and logs (availability beats a perfect count, NFR-05).
"""

from __future__ import annotations

import logging
from typing import Protocol

from redis.exceptions import RedisError

from tradelens.core.errors import rate_limited

log = logging.getLogger("tradelens.core.rate_limit")


class CounterStore(Protocol):
    """The part of a Redis client the limiter uses."""

    def incr(self, name: str) -> int:
        """Increment and return the counter."""
        ...

    def expire(self, name: str, time: int) -> object:
        """Set a TTL in seconds."""
        ...

    def ttl(self, name: str) -> int:
        """Seconds left, -1 without TTL, -2 when missing."""
        ...


def hit(store: CounterStore, key: str, limit: int, window_s: int = 60) -> int | None:
    """Count one request.

    Args:
        store: Redis client.
        key: Counter name, e.g. ``rl:login:acct:<email>``.
        limit: Requests allowed per window.
        window_s: Window length in seconds.

    Returns:
        None when allowed, else the seconds until the window resets (at least 1).
    """
    name = f"rl:{key}"
    try:
        count = int(store.incr(name))
        if count == 1:
            store.expire(name, window_s)
        if count <= limit:
            return None
        left = int(store.ttl(name))
        if left < 0:  # a counter without TTL (lost EXPIRE): give it one
            store.expire(name, window_s)
            left = window_s
        return max(left, 1)
    except (RedisError, OSError) as exc:
        log.warning("rate limiter unavailable; allowing", extra={"error": type(exc).__name__})
        return None


def enforce(store: CounterStore, key: str, limit: int, window_s: int = 60) -> None:
    """Like :func:`hit` but raise 429 ``rate_limited`` when over the limit."""
    retry = hit(store, key, limit, window_s)
    if retry is not None:
        raise rate_limited(retry)
