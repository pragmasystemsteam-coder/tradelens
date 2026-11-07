"""Building 15m/1h from 5m and 4H/1D from 1H (CR-004 D2-1, D2-3, FR-DATA-04)."""

from datetime import UTC, datetime, timedelta

from tradelens.modules.market_data.aggregate import aggregate
from tradelens.modules.market_data.candles import to_stored
from tradelens.modules.market_data.ports import RawBar

from .cal_fixtures import FX, METAL, ny


def series(start, tf_minutes, ohlcs, instrument="EUR_USD", tf="1h"):
    return [
        to_stored(RawBar(start + timedelta(minutes=tf_minutes * i), *ohlc), instrument, tf, "fake")
        for i, ohlc in enumerate(ohlcs)
    ]


def test_aggregate_ohlc():
    start = ny(2026, 11, 10, 17, 0)
    bars = series(start, 60, [(10, 15, 9, 12), (12, 20, 11, 18), (18, 19, 5, 6), (6, 8, 4, 7)])
    out = aggregate(FX, "1h", "4h", bars, now=start + timedelta(hours=4))
    assert len(out) == 1
    c = out[0]
    assert (c.open_time, c.timeframe, c.instrument) == (start, "4h", "EUR_USD")
    assert (c.o, c.h, c.l, c.c) == (10, 20, 4, 7)
    assert c.close_time == start + timedelta(hours=4)
    assert c.source == "fake"


def test_incomplete_bucket_not_built():
    start = ny(2026, 11, 10, 17, 0)
    bars = series(start, 60, [(10, 15, 9, 12)] * 4)
    assert (
        aggregate(FX, "1h", "4h", bars, now=start + timedelta(hours=4) - timedelta(seconds=1)) == []
    )
    holed = [b for b in bars if b.open_time != start + timedelta(hours=2)]
    assert aggregate(FX, "1h", "4h", holed, now=start + timedelta(hours=5)) == []


def test_metal_4h_bucket_built_from_three_bars():
    start = ny(2026, 11, 10, 18, 0)  # 17:00-18:00 is the daily break
    bars = series(start, 60, [(10, 15, 9, 12), (12, 20, 11, 18), (18, 19, 5, 6)], "XAU_USD")
    out = aggregate(METAL, "1h", "4h", bars, now=ny(2026, 11, 10, 21, 0))
    assert [(c.open_time, c.o, c.h, c.l, c.c) for c in out] == [
        (ny(2026, 11, 10, 17, 0), 10, 20, 5, 6)
    ]


def test_daily_from_1h_on_17_ny():
    start = ny(2026, 11, 9, 17, 0)
    bars = series(start, 60, [(100 + i, 110 + i, 90 + i, 101 + i) for i in range(24)])
    out = aggregate(FX, "1h", "1d", bars, now=ny(2026, 11, 10, 17, 0))
    assert len(out) == 1
    d = out[0]
    assert d.open_time == start and d.close_time == ny(2026, 11, 10, 17, 0)
    assert (d.o, d.h, d.l, d.c) == (100, 133, 90, 124)


def test_15m_from_5m_utc_aligned():
    start = datetime(2026, 11, 10, 14, 0, tzinfo=UTC)
    bars = series(start, 5, [(1, 3, 1, 2), (2, 4, 2, 3), (3, 9, 3, 8), (8, 8, 7, 7)], tf="5m")
    out = aggregate(FX, "5m", "15m", bars, now=start + timedelta(minutes=20))
    assert [(c.open_time, c.o, c.h, c.l, c.c) for c in out] == [(start, 1, 9, 1, 8)]


def test_only_buckets_after_given_start():
    start = ny(2026, 11, 10, 17, 0)
    bars = series(start, 60, [(10, 15, 9, 12)] * 8)
    out = aggregate(FX, "1h", "4h", bars, now=start + timedelta(hours=8), after=start)
    assert [c.open_time for c in out] == [start + timedelta(hours=4)]
