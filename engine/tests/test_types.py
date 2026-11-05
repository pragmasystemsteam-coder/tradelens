from datetime import UTC, datetime, timedelta

import pytest

from tradelens_engine.types import TIMEFRAME_MINUTES, TIMEFRAMES, Candle

T = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)


def test_timeframes_and_minutes():
    assert TIMEFRAMES == ("5m", "15m", "1h", "4h", "1d")
    assert TIMEFRAME_MINUTES == {"5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}


def test_candle_of_sets_close_time():
    c = Candle.of(T, "15m", 100, 105, 99, 103, bid_c=102, ask_c=104)
    assert c.close_time == T + timedelta(minutes=15)
    assert (c.o, c.h, c.l, c.c, c.bid_c, c.ask_c) == (100, 105, 99, 103, 102, 104)


def test_candle_is_frozen():
    c = Candle.of(T, "5m", 100, 101, 100, 100, bid_c=100, ask_c=100)
    with pytest.raises(AttributeError):
        c.o = 1  # type: ignore[misc]


@pytest.mark.parametrize("bad", [100.0, True])
def test_candle_rejects_float_and_bool_prices(bad):
    with pytest.raises(ValueError):
        Candle.of(T, "5m", bad, 101, 99, 100, bid_c=100, ask_c=100)


@pytest.mark.parametrize(
    "o,h,l,c",
    [(100, 99, 98, 100), (100, 101, 101, 100), (100, 101, 99, 102), (100, 101, 99, 98)],
)
def test_candle_rejects_bad_high_low(o, h, l, c):
    with pytest.raises(ValueError):
        Candle.of(T, "5m", o, h, l, c, bid_c=c, ask_c=c)


def test_candle_rejects_ask_below_bid():
    with pytest.raises(ValueError):
        Candle.of(T, "5m", 100, 101, 99, 100, bid_c=101, ask_c=100)


def test_candle_rejects_naive_time():
    with pytest.raises(ValueError):
        Candle.of(datetime(2026, 11, 2, 10, 0), "5m", 100, 101, 99, 100, bid_c=100, ask_c=100)


def test_candle_rejects_close_not_after_open():
    with pytest.raises(ValueError):
        Candle(open_time=T, close_time=T, o=1, h=1, l=1, c=1, bid_c=1, ask_c=1)


def test_candle_rejects_unknown_timeframe():
    with pytest.raises(ValueError):
        Candle.of(T, "2h", 100, 101, 99, 100, bid_c=100, ask_c=100)
