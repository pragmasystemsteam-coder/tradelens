"""Live prices: snapshot key, throttled channel, staleness and reconnects (DD 8.1 task 1.9).

The Twelve Data FREE plan has no streaming prices (CR-004), so production ticks come from the
newest stored 5m candle; the stream logic is proven here with fake sources and a fake clock.
"""

import json
import threading
from datetime import UTC, datetime

from tradelens.core.keys import PRICE_STREAM_KEY, price_key, prices_channel
from tradelens.worker.prices import PriceBook, PriceTick, run_price_stream

from .memory_analysis import RecordingRedis

T = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)


def tick(instrument="EUR_USD", bid=108000, ask=108012, at=T):
    return PriceTick(instrument, bid, ask, (bid + ask) // 2, 5, at)


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def test_tick_writes_snapshot_and_publishes():
    redis, clock = RecordingRedis(), Clock()
    book = PriceBook(redis, clock, throttle_ms=500, stale_after_s=10)
    book.on_tick(tick())
    snap = json.loads(redis.values[price_key("EUR_USD")])
    assert snap == {"instrument": "EUR_USD", "bid": 108000, "ask": 108012, "mid": 108006,
                    "price_scale": 5, "time": "2026-11-11T12:00:00Z", "stale": False}  # fmt: skip
    assert redis.events("price") == [(prices_channel("EUR_USD"), snap)]
    assert float(redis.values[PRICE_STREAM_KEY]) == 1000.0


def test_channel_throttled_latest_tick_wins():
    redis, clock = RecordingRedis(), Clock()
    book = PriceBook(redis, clock, throttle_ms=500, stale_after_s=10)
    book.on_tick(tick(bid=1))
    clock.t += 0.1
    book.on_tick(tick(bid=2))
    clock.t += 0.1
    book.on_tick(tick(bid=3))
    assert [d["bid"] for _, d in redis.events("price")] == [1]
    assert json.loads(redis.values[price_key("EUR_USD")])["bid"] == 3  # snapshot always latest
    clock.t += 0.4
    book.flush()
    assert [d["bid"] for _, d in redis.events("price")] == [1, 3]
    book.flush()  # nothing pending
    assert len(redis.events("price")) == 2


def test_price_marked_stale_after_10s():
    redis, clock = RecordingRedis(), Clock()
    book = PriceBook(redis, clock, throttle_ms=500, stale_after_s=10)
    book.on_tick(tick())
    clock.t += 10
    book.check_stale()
    assert json.loads(redis.values[price_key("EUR_USD")])["stale"] is False  # exactly 10 s
    clock.t += 0.5
    book.check_stale()
    assert json.loads(redis.values[price_key("EUR_USD")])["stale"] is True
    assert redis.events("price")[-1][1]["stale"] is True
    book.check_stale()  # published once
    assert sum(1 for _, d in redis.events("price") if d["stale"]) == 1
    book.on_tick(tick(bid=5))  # a new tick clears it
    assert json.loads(redis.values[price_key("EUR_USD")])["stale"] is False


def test_price_stream_reconnects():
    redis, clock = RecordingRedis(), Clock()
    book = PriceBook(redis, clock, throttle_ms=0, stale_after_s=10)
    stop = threading.Event()
    connects, sleeps = [], []

    def connect():
        connects.append(len(connects))
        if len(connects) == 1:
            yield tick(bid=1)
            raise ConnectionError("stream dropped")
        if len(connects) == 2:
            raise OSError("cannot connect")
        yield tick(bid=2)
        stop.set()  # third connection works; end the test

    run_price_stream(connect, book, stop, sleep=sleeps.append, retry_s=2)
    assert len(connects) == 3
    assert sleeps == [2, 2]
    assert [d["bid"] for _, d in redis.events("price")] == [1, 2]


def test_price_stream_ending_normally_reconnects_too():
    redis, clock = RecordingRedis(), Clock()
    book = PriceBook(redis, clock, throttle_ms=0, stale_after_s=10)
    stop = threading.Event()
    calls = []

    def connect():
        calls.append(1)
        if len(calls) == 2:
            stop.set()
        return iter([tick()])

    run_price_stream(connect, book, stop, sleep=lambda s: None, retry_s=2)
    assert len(calls) == 2


def test_candle_source_publishes_only_new_closes_and_goes_stale(monkeypatch):
    """CR-004: the newest 5m close is re-read every poll, but only a new close is a tick.

    A source that stops getting new candles (ingest dead) must turn stale; the poll itself
    keeps the stream marker fresh so /healthz/full tells "stream alive" from "data old".
    """
    from datetime import timedelta

    from tradelens.modules.market_data.candles import StoredCandle
    from tradelens.worker import prices

    class Spec:
        code, price_scale = "EUR_USD", 5

    rows = [StoredCandle("EUR_USD", "5m", T, 1, 1, 1, 1, 1, 1, 1, 1, 2, 2, 2, 2, "db")]
    monkeypatch.setattr(prices, "latest_closes", lambda conn: list(rows))

    class Engine:
        def connect(self):
            import contextlib

            return contextlib.nullcontext(None)

    stop = threading.Event()
    polls = []
    connect = prices.candle_close_ticks(Engine(), [Spec()], stop, poll_s=0,
                                        on_poll=lambda: polls.append(1))  # fmt: skip
    ticks = connect()
    first = next(ticks)
    assert first.time == T + timedelta(minutes=5)
    rows[0] = StoredCandle("EUR_USD", "5m", T + timedelta(minutes=5), 3, 3, 3, 3, 3, 3, 3, 3,
                           4, 4, 4, 4, "db")  # fmt: skip
    second = next(ticks)  # the unchanged first candle was skipped on the next poll
    assert second.bid == 3
    assert len(polls) >= 2


def test_mark_alive_writes_stream_marker_without_tick():
    redis, clock = RecordingRedis(), Clock(500.0)
    book = PriceBook(redis, clock, throttle_ms=0, stale_after_s=10)
    book.mark_alive()
    assert float(redis.values[PRICE_STREAM_KEY]) == 500.0
    assert redis.events("price") == []


def test_stale_watch_survives_unexpected_errors():
    from tradelens.worker.prices import run_stale_watch

    stop = threading.Event()
    calls = []

    class Book:
        def check_stale(self):
            calls.append(1)
            if len(calls) == 1:
                raise KeyError("bad row")
            stop.set()

        def flush(self):
            pass

    run_stale_watch(Book(), stop, interval_s=0)
    assert len(calls) == 2


def test_price_stream_survives_unexpected_errors():
    redis, clock = RecordingRedis(), Clock()
    book = PriceBook(redis, clock, throttle_ms=0, stale_after_s=10)
    stop = threading.Event()
    calls = []

    def connect():
        calls.append(1)
        if len(calls) == 1:
            raise KeyError("bad row")
        stop.set()
        return iter([])

    run_price_stream(connect, book, stop, sleep=lambda s: None, retry_s=0)
    assert len(calls) == 2
