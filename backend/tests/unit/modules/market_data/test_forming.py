"""The forming (unfinished) candle built from stored 5m candles, for display only."""

from datetime import UTC, datetime, timedelta

from tradelens.modules.market_data.aggregate import bucket_close, forming_candle
from tradelens.modules.market_data.candles import to_stored
from tradelens.modules.market_data.ports import RawBar


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


def m5(start, ohlcs, instrument="EUR_USD"):
    return [
        to_stored(RawBar(start + timedelta(minutes=5 * i), *ohlc), instrument, "5m", "twelvedata")
        for i, ohlc in enumerate(ohlcs)
    ]


def test_15m_from_the_5m_candles_of_the_open_period():
    bars = m5(utc(2026, 11, 18, 10, 0), [(10, 15, 9, 12), (12, 20, 11, 18)])
    f = forming_candle("15m", bars, last_closed=utc(2026, 11, 18, 9, 45),
                       now=utc(2026, 11, 18, 10, 11))  # fmt: skip
    assert f is not None
    assert (f.open_time, f.timeframe) == (utc(2026, 11, 18, 10, 0), "15m")
    assert (f.o, f.h, f.l, f.c) == (10, 20, 9, 18)
    assert f.closes_at == utc(2026, 11, 18, 10, 15)


def test_only_candles_inside_the_period_count():
    bars = m5(utc(2026, 11, 18, 9, 50), [(1, 99, 1, 2), (2, 3, 1, 2), (12, 14, 11, 13)])
    f = forming_candle("15m", bars, last_closed=utc(2026, 11, 18, 9, 45),
                       now=utc(2026, 11, 18, 10, 7))  # fmt: skip
    assert f is not None
    assert (f.o, f.h, f.l, f.c) == (12, 14, 11, 13)


def test_1h_is_aligned_to_utc():
    bars = m5(utc(2026, 11, 18, 14, 0), [(5, 6, 4, 5)] * 7)
    f = forming_candle("1h", bars, last_closed=utc(2026, 11, 18, 13, 0),
                       now=utc(2026, 11, 18, 14, 36))  # fmt: skip
    assert f is not None
    assert f.open_time == utc(2026, 11, 18, 14, 0)
    assert f.closes_at == utc(2026, 11, 18, 15, 0)


def test_4h_on_the_17_00_new_york_day_in_summer():
    # 08:00 EDT is in the 05:00-09:00 New York bucket = 09:00-13:00 UTC.
    bars = m5(utc(2026, 7, 15, 9, 0), [(5, 6, 4, 5)] * 36)
    f = forming_candle("4h", bars, last_closed=utc(2026, 7, 15, 5, 0),
                       now=utc(2026, 7, 15, 12, 0))  # fmt: skip
    assert f is not None
    assert f.open_time == utc(2026, 7, 15, 9, 0)
    assert f.closes_at == utc(2026, 7, 15, 13, 0)


def test_4h_and_1d_in_the_week_daylight_saving_ends():
    # US clocks go back on Sunday 1 Nov 2026: the trading day opens 17:00 EST = 22:00 UTC.
    now = utc(2026, 11, 2, 3, 0)
    bars = m5(utc(2026, 11, 2, 2, 0), [(5, 6, 4, 5)] * 12)
    f4 = forming_candle("4h", bars, last_closed=utc(2026, 11, 1, 22, 0), now=now)
    assert f4 is not None
    assert (f4.open_time, f4.closes_at) == (utc(2026, 11, 2, 2, 0), utc(2026, 11, 2, 6, 0))
    day = m5(utc(2026, 11, 1, 22, 0), [(5, 6, 4, 5)] * 60)
    f1 = forming_candle("1d", day, last_closed=utc(2026, 10, 29, 21, 0), now=now)
    assert f1 is not None
    assert (f1.open_time, f1.closes_at) == (utc(2026, 11, 1, 22, 0), utc(2026, 11, 2, 22, 0))


def test_bucket_close_follows_new_york_wall_clock():
    # Sat 31 Oct 17:00 EDT (21:00 UTC) to Sun 1 Nov 17:00 EST (22:00 UTC): a 25-hour day.
    assert bucket_close("1d", utc(2026, 10, 31, 21, 0)) == utc(2026, 11, 1, 22, 0)
    assert bucket_close("4h", utc(2026, 11, 1, 22, 0)) == utc(2026, 11, 2, 2, 0)
    assert bucket_close("15m", utc(2026, 10, 31, 21, 0)) == utc(2026, 10, 31, 21, 15)


def test_none_for_5m_without_data_or_when_already_finished():
    bars = m5(utc(2026, 11, 18, 10, 0), [(10, 15, 9, 12)])
    now = utc(2026, 11, 18, 10, 7)
    assert forming_candle("5m", bars, last_closed=utc(2026, 11, 18, 9, 55), now=now) is None
    assert forming_candle("15m", [], last_closed=utc(2026, 11, 18, 9, 45), now=now) is None
    # The 10:00 15m candle is already stored as finished.
    assert forming_candle("15m", bars, last_closed=utc(2026, 11, 18, 10, 0), now=now) is None


def test_none_when_the_5m_candles_are_from_an_older_period():
    bars = m5(utc(2026, 11, 18, 9, 45), [(10, 15, 9, 12)] * 3)
    f = forming_candle("15m", bars, last_closed=utc(2026, 11, 18, 9, 45),
                       now=utc(2026, 11, 18, 10, 20))  # fmt: skip
    assert f is None


def test_5m_candles_not_yet_closed_are_ignored():
    # The 10:05 row closes at 10:10; at 10:08 it is not finished, so only 10:00 counts.
    bars = m5(utc(2026, 11, 18, 10, 0), [(10, 12, 9, 11), (11, 30, 1, 29)])
    f = forming_candle("15m", bars, last_closed=utc(2026, 11, 18, 9, 45),
                       now=utc(2026, 11, 18, 10, 8))  # fmt: skip
    assert f is not None
    assert (f.h, f.l, f.c) == (12, 9, 11)
