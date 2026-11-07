"""Trading calendars, expected candles and gaps (FR-DATA-04, FR-DATA-09, DD 7.2 Calendars)."""

from datetime import UTC, datetime, timedelta

from tradelens.modules.market_data.calendar import (
    bucket_open,
    expected_open_times,
    find_gaps,
    is_open,
)

from .cal_fixtures import FX, METAL, NY, ny


def test_sunday_open_expected():
    times = expected_open_times(FX, "1h", ny(2026, 11, 8, 15, 0), ny(2026, 11, 8, 19, 0))
    assert times == [ny(2026, 11, 8, 17, 0), ny(2026, 11, 8, 18, 0)]


def test_saturday_not_expected():
    assert expected_open_times(FX, "5m", ny(2026, 11, 7, 0, 0), ny(2026, 11, 8, 0, 0)) == []
    assert not is_open(FX, ny(2026, 11, 7, 12, 0))


def test_friday_close_is_last():
    times = expected_open_times(FX, "1h", ny(2026, 11, 6, 15, 0), ny(2026, 11, 6, 19, 0))
    assert times == [ny(2026, 11, 6, 15, 0), ny(2026, 11, 6, 16, 0)]


def test_metal_break_not_expected():
    times = expected_open_times(METAL, "1h", ny(2026, 11, 10, 15, 0), ny(2026, 11, 10, 20, 0))
    assert times == [
        ny(2026, 11, 10, 15, 0),
        ny(2026, 11, 10, 16, 0),
        ny(2026, 11, 10, 18, 0),
        ny(2026, 11, 10, 19, 0),
    ]
    assert not is_open(METAL, ny(2026, 11, 10, 17, 30))
    assert is_open(FX, ny(2026, 11, 10, 17, 30))


def test_metal_opens_sunday_18():
    times = expected_open_times(METAL, "1h", ny(2026, 11, 8, 16, 0), ny(2026, 11, 8, 20, 0))
    assert times == [ny(2026, 11, 8, 18, 0), ny(2026, 11, 8, 19, 0)]


def test_gap_only_if_later_candle_exists():
    start = ny(2026, 11, 10, 9, 0)
    stored = [start, start + timedelta(minutes=5), start + timedelta(minutes=20)]
    gaps = find_gaps(FX, "5m", stored)
    # gap_to is the close of the last missing candle (exclusive end, as data_gaps stores it)
    assert gaps == [(start + timedelta(minutes=10), start + timedelta(minutes=20))]
    # Nothing after the last stored candle is a gap (it may simply not be complete yet).
    assert find_gaps(FX, "5m", stored[:2]) == []


def test_weekend_and_metal_break_are_not_gaps():
    fri = ny(2026, 11, 6, 16, 0)
    sun = ny(2026, 11, 8, 17, 0)
    assert find_gaps(FX, "1h", [fri, sun]) == []
    assert find_gaps(METAL, "1h", [ny(2026, 11, 10, 16, 0), ny(2026, 11, 10, 18, 0)]) == []


def test_daily_alignment_17_ny():
    assert bucket_open("1d", ny(2026, 11, 10, 9, 30)) == ny(2026, 11, 9, 17, 0)
    assert bucket_open("1d", ny(2026, 11, 10, 17, 0)) == ny(2026, 11, 10, 17, 0)


def test_daily_bucket_17ny_both_dst():
    # US DST: 8 Mar to 1 Nov 2026. 17:00 NY is 21:00 UTC in summer and 22:00 UTC in winter.
    def utc(*a):
        return datetime(*a, tzinfo=UTC)

    assert bucket_open("1d", utc(2026, 3, 10, 12, 0)) == utc(2026, 3, 9, 21, 0)
    assert bucket_open("1d", utc(2026, 3, 5, 12, 0)) == utc(2026, 3, 4, 22, 0)
    assert bucket_open("1d", utc(2026, 10, 28, 12, 0)) == utc(2026, 10, 27, 21, 0)
    assert bucket_open("1d", utc(2026, 11, 3, 12, 0)) == utc(2026, 11, 2, 22, 0)


def test_4h_buckets_17_21_01_05_09_13_ny():
    day = ny(2026, 11, 10, 17, 0)
    opens = {bucket_open("4h", day + timedelta(hours=h)) for h in range(24)}
    assert sorted(t.astimezone(NY).hour for t in opens) == [1, 5, 9, 13, 17, 21]


def test_intraday_buckets_utc_aligned():
    t = datetime(2026, 11, 10, 14, 37, tzinfo=UTC)
    assert bucket_open("15m", t) == datetime(2026, 11, 10, 14, 30, tzinfo=UTC)
    assert bucket_open("1h", t) == datetime(2026, 11, 10, 14, 0, tzinfo=UTC)
    assert bucket_open("5m", t) == datetime(2026, 11, 10, 14, 35, tzinfo=UTC)


def test_expected_4h_metal_includes_partial_bucket():
    times = expected_open_times(METAL, "4h", ny(2026, 11, 10, 13, 0), ny(2026, 11, 11, 1, 0))
    assert times == [ny(2026, 11, 10, 13, 0), ny(2026, 11, 10, 17, 0), ny(2026, 11, 10, 21, 0)]


def test_saturday_daily_bucket_before_spring_dst_not_expected():
    """Review L11: Sat 17:00 NY bucket is 23 real hours in March; it never reaches Sunday's open."""
    from tradelens.modules.market_data.calendar import is_expected

    assert not is_expected(FX, "1d", ny(2026, 3, 7, 17, 0))
    assert is_expected(FX, "1d", ny(2026, 3, 8, 17, 0))
    assert not is_expected(FX, "1d", ny(2026, 10, 31, 17, 0))
