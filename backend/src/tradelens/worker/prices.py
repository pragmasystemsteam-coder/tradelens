"""Live prices: Redis snapshot, throttled channel, staleness and reconnects (DD 4.4; task 1.9).

``price:{instrument}`` always holds the latest tick as JSON (``stale`` true once no tick came
for ``PRICE_STALE_AFTER_SECONDS``). ``prices:{instrument}`` gets at most one message every
``SSE_PRICE_THROTTLE_MS`` per instrument; the latest tick wins. ``worker:prices`` holds the
Unix time of the last tick, for ``/healthz/full``.

CR-004: the Twelve Data FREE plan has no streaming prices, so :func:`candle_close_ticks`
turns each new stored 5m close into a tick (price as of the last close, ``time`` = that
candle's close). The worker then uses a stale limit of one candle plus grace (420 s), so a
missing close still turns the price stale. An OANDA pricing stream can replace it
later behind the same ``connect`` callable.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime

from redis.exceptions import RedisError
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

from tradelens.core.keys import PRICE_STREAM_KEY, price_key, prices_channel
from tradelens.modules.market_data.public import InstrumentSpec, latest_closes
from tradelens.worker.publish import Publisher, iso, send

log = logging.getLogger("tradelens.worker.prices")
DEFAULT_THROTTLE_MS = 500
DEFAULT_STALE_AFTER_S = 10
DEFAULT_RETRY_S = 2.0
DEFAULT_POLL_S = 5.0
MS = 1000


@dataclass(frozen=True, slots=True)
class PriceTick:
    """One price: integer bid, ask and mid in smallest units (AD-12)."""

    instrument: str
    bid: int
    ask: int
    mid: int
    price_scale: int
    time: datetime

    def to_json(self, *, stale: bool) -> dict[str, object]:
        """The snapshot / message body (DD 4.4 ``price`` event plus ``stale``)."""
        return {
            "instrument": self.instrument, "bid": self.bid, "ask": self.ask, "mid": self.mid,
            "price_scale": self.price_scale, "time": iso(self.time), "stale": stale,
        }  # fmt: skip


@dataclass(slots=True)
class _Entry:
    tick: PriceTick
    received: float
    published: float | None = None
    pending: bool = False
    stale: bool = False


class PriceBook:
    """Latest tick per instrument; thread-safe (stream thread and stale watchdog)."""

    def __init__(
        self,
        publisher: Publisher,
        clock: Callable[[], float],
        *,
        throttle_ms: int = DEFAULT_THROTTLE_MS,
        stale_after_s: float = DEFAULT_STALE_AFTER_S,
    ) -> None:
        self._pub = publisher
        self._clock = clock
        self._throttle = throttle_ms / MS
        self._stale_after = stale_after_s
        self._entries: dict[str, _Entry] = {}
        self._lock = threading.Lock()

    def _snapshot(self, entry: _Entry, *, publish: bool) -> tuple[str, dict[str, object], bool]:
        """Decide under the lock; the Redis I/O happens after the lock is released."""
        if publish:
            entry.published = self._clock()
            entry.pending = False
        return entry.tick.instrument, entry.tick.to_json(stale=entry.stale), publish

    def _send(self, writes: list[tuple[str, dict[str, object], bool]]) -> None:
        for instrument, body, publish in writes:
            try:
                self._pub.set(price_key(instrument), json.dumps(body))
            except (RedisError, OSError) as exc:
                log.warning("price snapshot failed", extra={"error": type(exc).__name__})
            if publish:
                send(self._pub, prices_channel(instrument), "price", body)

    def mark_alive(self) -> None:
        """Record that the stream (or the candle poll) is running, for ``/healthz/full``."""
        try:
            self._pub.set(PRICE_STREAM_KEY, str(self._clock()))
        except (RedisError, OSError) as exc:
            log.warning("price stream marker failed", extra={"error": type(exc).__name__})

    def on_tick(self, tick: PriceTick) -> None:
        """Store a tick; publish it now unless the instrument published within the throttle."""
        now = self._clock()
        with self._lock:
            entry = self._entries.get(tick.instrument)
            if entry is None:
                entry = self._entries[tick.instrument] = _Entry(tick, now)
            entry.tick, entry.received, entry.stale = tick, now, False
            due = entry.published is None or now - entry.published >= self._throttle
            entry.pending = not due
            writes = [self._snapshot(entry, publish=due)]
        self._send(writes)
        self.mark_alive()

    def flush(self) -> None:
        """Publish held-back ticks whose throttle window has passed (latest tick wins)."""
        now = self._clock()
        with self._lock:
            writes = [
                self._snapshot(entry, publish=True)
                for entry in self._entries.values()
                if entry.pending and now - (entry.published or 0.0) >= self._throttle
            ]
        self._send(writes)

    def check_stale(self) -> None:
        """Mark (once) every instrument without a tick for longer than the stale limit."""
        now = self._clock()
        with self._lock:
            writes = []
            for entry in self._entries.values():
                if not entry.stale and now - entry.received > self._stale_after:
                    entry.stale = True
                    writes.append(self._snapshot(entry, publish=True))
        self._send(writes)


def run_price_stream(
    connect: Callable[[], Iterable[PriceTick]],
    book: PriceBook,
    stop: threading.Event,
    *,
    sleep: Callable[[float], object] | None = None,
    retry_s: float = DEFAULT_RETRY_S,
) -> None:
    """Consume ticks until ``stop``; reconnect after ``retry_s`` when the stream fails or ends.

    Args:
        connect: Opens the stream and returns its ticks (a generator is fine).
        book: Where ticks go.
        stop: Ends the loop.
        sleep: Wait between reconnects (default ``stop.wait``, so stopping is immediate).
        retry_s: Seconds before reconnecting.
    """
    wait = sleep or stop.wait
    while not stop.is_set():
        try:
            for tick in connect():
                book.on_tick(tick)
                book.flush()
                if stop.is_set():
                    return
        except (OSError, SQLAlchemyError) as exc:  # ConnectionError is an OSError
            log.warning("price stream failed; reconnecting", extra={"error": type(exc).__name__})
        except Exception:  # never let the thread die silently (the heartbeat would hide it)
            log.exception("price stream crashed; reconnecting")
        if not stop.is_set():
            wait(retry_s)


def run_stale_watch(book: PriceBook, stop: threading.Event, interval_s: float = 1.0) -> None:
    """Check staleness every ``interval_s`` until ``stop`` (runs beside the stream)."""
    while not stop.wait(interval_s):
        try:
            book.check_stale()
            book.flush()
        except Exception:  # keep watching; a crash here would hide stale prices
            log.exception("stale watch failed")


def candle_close_ticks(
    engine: Engine, specs: Sequence[InstrumentSpec], stop: threading.Event,
    poll_s: float = DEFAULT_POLL_S, on_poll: Callable[[], object] | None = None,
) -> Callable[[], Iterator[PriceTick]]:  # fmt: skip
    """A ``connect`` callable that yields each instrument's newest stored 5m close once.

    The database is polled every ``poll_s``; a close is yielded only when it is new, so the
    price turns stale when no new candle arrives (ingest delayed or dead). ``on_poll`` runs
    after every poll (the worker passes ``PriceBook.mark_alive``). Database errors end the
    generator with the error, so :func:`run_price_stream` reconnects.
    """
    scales = {s.code: s.price_scale for s in specs}

    def connect() -> Iterator[PriceTick]:
        seen: dict[str, datetime] = {}
        while not stop.is_set():
            with engine.connect() as conn:
                rows = latest_closes(conn)
            if on_poll is not None:
                on_poll()
            for r in rows:
                if r.instrument in scales and seen.get(r.instrument) != r.close_time:
                    seen[r.instrument] = r.close_time
                    yield PriceTick(r.instrument, r.bid_c, r.ask_c, r.c, scales[r.instrument],
                                    r.close_time)  # fmt: skip
            stop.wait(poll_s)

    return connect
