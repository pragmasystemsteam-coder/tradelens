"""Live messages from the worker to the API over Redis pub/sub (DD 4.4; AD-06; task 1.9).

Every message is ``{"event": <SSE event name>, "data": {...}}`` as JSON; the API forwards it
to browsers subscribed to the topic. Publishing never stops the worker: a Redis error is
logged and the next close publishes again (the browser also refetches on reconnect).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Protocol

from redis.exceptions import RedisError

from tradelens.core.keys import DATA_CHANNEL, updates_channel

log = logging.getLogger("tradelens.worker.publish")
TIMEFRAMES = ("5m", "15m", "1h", "4h", "1d")


class Publisher(Protocol):
    """The part of a Redis client the worker publishes with."""

    def publish(self, channel: str, message: str) -> object:
        """Publish ``message`` on ``channel``."""
        ...

    def set(self, name: str, value: str, ex: int | None = None) -> object:
        """Store ``value`` under ``name`` with an optional TTL in seconds."""
        ...


def iso(t: datetime) -> str:
    """UTC time as ``YYYY-MM-DDTHH:MM:SSZ``."""
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def send(publisher: Publisher, channel: str, event: str, data: Mapping[str, Any]) -> bool:
    """Publish one message; return False (and log) when Redis is unavailable."""
    try:
        publisher.publish(channel, json.dumps({"event": event, "data": dict(data)}))
    except (RedisError, OSError) as exc:
        log.warning("publish failed", extra={"channel": channel, "error": type(exc).__name__})
        return False
    return True


def chart_updated(
    publisher: Publisher, instrument: str, last_close: Mapping[str, datetime]
) -> None:
    """``chart.updated`` on ``updates:{instrument}`` for every timeframe that was stepped."""
    for tf, t in last_close.items():
        send(publisher, updates_channel(instrument), "chart.updated",
             {"instrument": instrument, "timeframe": tf, "last_close": iso(t)})  # fmt: skip


def status_changed(
    publisher: Publisher, instrument: str, status: str, previous: str | None, since: datetime
) -> None:
    """``series.delayed`` / ``series.resumed`` on ``data`` when the status changed.

    A worker that starts with an unknown previous status announces a delay but not a resume.
    """
    if status == "delayed" and previous != "delayed":
        event = "series.delayed"
    elif status == "ok" and previous == "delayed":
        event = "series.resumed"
    else:
        return
    for tf in TIMEFRAMES:
        send(publisher, DATA_CHANNEL, event,
             {"instrument": instrument, "timeframe": tf, "since": iso(since)})  # fmt: skip
