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

from tradelens.core.keys import DATA_CHANNEL, SCANNER_CHANNEL, scanner_key, updates_channel

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


def scanner_updated(
    publisher: Publisher,
    groups: Mapping[tuple[str, str], list[dict[str, Any]]],
    data_as_of: datetime,
) -> bool:
    """Store every ``scanner:{direction}:{timeframe}`` list, then send ``scanner.updated``.

    The cache is written before the message, so a browser that refetches on the message reads
    the new list. Returns False when Redis is unavailable (the API then reads the database).
    """
    as_of = iso(data_as_of)
    try:
        for (direction, tf), rows in groups.items():
            doc = {"data_as_of": as_of, "items": rows}
            publisher.set(scanner_key(direction, tf), json.dumps(doc))
    except (RedisError, OSError) as exc:
        log.warning("scanner cache write failed", extra={"error": type(exc).__name__})
        return False
    for tf in sorted({tf for _, tf in groups}):
        send(publisher, SCANNER_CHANNEL, "scanner.updated", {"timeframe": tf, "data_as_of": as_of})
    return True


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
