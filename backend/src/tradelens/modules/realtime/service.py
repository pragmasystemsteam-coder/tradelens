"""Server-Sent Events over Redis pub/sub (DD 4.4; AD-06, AD-07; task 2.8).

One async generator per connection. Messages only say what changed; the browser refetches
over REST, and after a reconnect it refetches everything it shows. ``price`` goes out at
most every ``SSE_PRICE_THROTTLE_MS`` per instrument (latest tick wins), a ``: ping`` comment
every 25 s, and ``session.ended`` for this session closes the stream. A user may hold
``SSE_MAX_STREAMS_PER_USER`` (6) streams. Each open stream is a member of the Redis sorted
set ``sse:slots:{user_id}`` scored by its last ping; a stream that died without closing (an API
restart, a crash) lapses after ``SLOT_STALE_SECONDS``, so it never blocks the user for long.
"""

from __future__ import annotations

import inspect
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from tradelens.core.errors import rate_limited, validation_error
from tradelens.core.keys import (
    DATA_CHANNEL,
    SCANNER_CHANNEL,
    prices_channel,
    updates_channel,
    user_channel,
)
from tradelens.core.limits import Limits

log = logging.getLogger("tradelens.realtime")
MAX_TOPICS = 20
SLOT_STALE_SECONDS = 90  # 3 missed 25 s pings: the stream is gone
SLOT_KEY_TTL_SECONDS = 2 * SLOT_STALE_SECONDS


def slot_key(user_id: str) -> str:
    """The sorted set of a user's open streams (the older ``sse:{id}`` counter is retired)."""
    return f"sse:slots:{user_id}"


RETRY_MS = 3000


@dataclass(frozen=True, slots=True)
class StreamSpec:
    """What one stream forwards."""

    user_id: str
    session_id: str
    channels: tuple[str, ...]
    instruments: frozenset[str] | set[str]  # entitled instruments (data and price filters)
    throttle_s: float = 0.5
    ping_s: float = 25.0
    poll_s: float = 1.0  # how often a quiet stream checks for a disconnect


def parse_topics(
    topics: str, instruments: Mapping[str, str], limits: Limits, *, user_id: str
) -> tuple[str, ...]:
    """Redis channels for ``?topics=scanner,chart:X,price:X`` plus ``data`` and ``user``.

    Raises:
        ApiError: 400 ``validation_error`` on more than 20 topics, an unknown topic or
            instrument; 403 ``plan_required`` for a commodity the plan does not include.
    """
    names = [t.strip() for t in topics.split(",") if t.strip()]
    if len(names) > MAX_TOPICS:
        raise validation_error("topics", "too_many")
    channels = [DATA_CHANNEL, user_channel(user_id)]
    for name in names:
        kind, _, code = name.partition(":")
        if kind == "scanner" and not code:
            channels.append(SCANNER_CHANNEL)
            continue
        if kind not in ("chart", "price") or code not in instruments:
            raise validation_error("topics", f"unknown topic {name[:40]}")
        limits.require_asset(instruments[code])
        channels.append(updates_channel(code) if kind == "chart" else prices_channel(code))
    return tuple(dict.fromkeys(channels))


async def acquire_stream(
    aredis: Any,  # noqa: ANN401
    user_id: str,
    max_streams: int,
    now: Callable[[], float] = time.time,
) -> str:
    """Take one of the user's stream slots and return its ID.

    Slots whose last ping is older than ``SLOT_STALE_SECONDS`` are dropped first.

    Raises:
        ApiError: 429 ``rate_limited`` when all slots are taken.
    """
    key, t, slot = slot_key(user_id), now(), uuid.uuid4().hex
    await aredis.zremrangebyscore(key, 0, t - SLOT_STALE_SECONDS)
    await aredis.zadd(key, {slot: t})
    await aredis.expire(key, SLOT_KEY_TTL_SECONDS)
    if int(await aredis.zcard(key)) > max_streams:
        await aredis.zrem(key, slot)
        raise rate_limited(5)
    return slot


async def keep_stream(
    aredis: Any,  # noqa: ANN401
    user_id: str,
    slot: str,
    now: Callable[[], float] = time.time,
) -> None:
    """Mark the stream alive (called at each ping)."""
    key = slot_key(user_id)
    try:
        await aredis.zadd(key, {slot: now()})
        await aredis.expire(key, SLOT_KEY_TTL_SECONDS)
    except Exception:  # noqa: BLE001 - a missed refresh must not end the stream
        log.warning("stream slot refresh failed", extra={"user_id": user_id})


async def release_stream(aredis: Any, user_id: str, slot: str) -> None:  # noqa: ANN401
    """Give a slot back when a stream closes (an unknown or lapsed slot is ignored)."""
    try:
        await aredis.zrem(slot_key(user_id), slot)
    except Exception:  # noqa: BLE001 - closing must never raise
        log.warning("stream slot release failed", extra={"user_id": user_id})


def frame(event: str, data: Mapping[str, Any]) -> str:
    """One SSE message."""
    return f"event: {event}\ndata: {json.dumps(dict(data), separators=(',', ':'))}\n\n"


async def event_stream(
    pubsub: Any,  # noqa: ANN401 - redis.asyncio PubSub (a fake in tests)
    spec: StreamSpec,
    *,
    monotonic: Callable[[], float] = time.monotonic,
    disconnected: Callable[[], Awaitable[bool]] | None = None,
    on_ping: Callable[[], object] | None = None,
) -> AsyncIterator[str]:
    """Forward subscribed Redis messages as SSE frames until the client leaves.

    Args:
        pubsub: A pub/sub object (``subscribe``, ``get_message``, ``aclose``).
        spec: Channels, session and timings.
        monotonic: Clock for throttling and the heartbeat (frozen in tests).
        disconnected: Returns True once the client has gone.
        on_ping: Called (and awaited when it returns an awaitable) at each ping, e.g. to keep
            the stream slot key alive while the stream stays open.

    Yields:
        SSE frames: the retry hint first, then events and ``: ping`` comments.
    """
    await pubsub.subscribe(*spec.channels)
    last_ping = monotonic()
    sent_at: dict[str, float] = {}
    pending: dict[str, dict[str, Any]] = {}
    try:
        yield f"retry: {RETRY_MS}\n\n"
        while True:
            if disconnected is not None and await disconnected():
                return
            now = monotonic()
            for inst in [i for i in pending if now - sent_at.get(i, -1e18) >= spec.throttle_s]:
                sent_at[inst] = now
                yield frame("price", pending.pop(inst))
            if now - last_ping >= spec.ping_s:
                last_ping = now
                if on_ping is not None:
                    done = on_ping()
                    if inspect.isawaitable(done):
                        await done
                yield ": ping\n\n"
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=spec.poll_s)
            if msg is None or msg.get("type") != "message":
                continue
            try:
                body = json.loads(msg["data"])
                event, data = str(body["event"]), dict(body["data"])
            except (ValueError, KeyError, TypeError):
                log.warning("bad pub/sub message", extra={"channel": msg.get("channel")})
                continue
            if event == "price":
                inst = str(data.get("instrument"))
                now = monotonic()
                if now - sent_at.get(inst, -1e18) >= spec.throttle_s:
                    sent_at[inst] = now
                    pending.pop(inst, None)
                    yield frame("price", data)
                else:
                    pending[inst] = data  # latest tick wins
                continue
            if event == "session.ended":
                if spec.session_id in data.get("sessions", []):
                    yield frame("session.ended", {"reason": data.get("reason", "ended")})
                    return
                continue
            on_data = msg.get("channel") == DATA_CHANNEL
            if on_data and data.get("instrument") not in spec.instruments:
                continue
            yield frame(event, data)
    finally:
        try:
            await pubsub.aclose()
        except Exception:  # noqa: BLE001 - closing must never raise
            log.warning("pubsub close failed")
