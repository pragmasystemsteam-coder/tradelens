from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from tradelens_engine.timekeys import ny_day_key, ny_week_key, sessions_of

NY = ZoneInfo("America/New_York")


def ny(y, m, d, h, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=NY).astimezone(UTC)


@pytest.mark.parametrize("month,day,utc_hour_at_17", [(1, 14, 22), (7, 15, 21)])
def test_day_key_17ny_both_dst(month, day, utc_hour_at_17):
    before, at17 = ny(2026, month, day, 16, 59), ny(2026, month, day, 17, 0)
    assert at17.hour == utc_hour_at_17  # proves both EST and EDT are exercised
    assert ny_day_key(before) == date(2026, month, day)
    assert ny_day_key(at17) == date(2026, month, day + 1)


def test_day_key_dst_switch_week():
    # DST ends Sunday 1 Nov 2026; the market reopens 17:00 New York (EST) that day.
    assert ny_day_key(ny(2026, 11, 1, 17, 0)) == date(2026, 11, 2)
    assert ny_day_key(ny(2026, 10, 30, 16, 59)) == date(2026, 10, 30)


def test_day_key_rejects_naive():
    with pytest.raises(ValueError):
        ny_day_key(datetime(2026, 11, 2, 10, 0))


def test_week_key_sunday_open_is_next_week():
    friday_close = ny(2026, 11, 6, 16, 59)
    sunday_open = ny(2026, 11, 8, 17, 0)
    year, week, _ = date(2026, 11, 9).isocalendar()
    assert ny_week_key(sunday_open) == f"{year}-W{week:02d}"
    assert ny_week_key(friday_close) != ny_week_key(sunday_open)
    assert ny_week_key(ny(2026, 11, 2, 3)) == ny_week_key(friday_close)


@pytest.mark.parametrize(
    "hour,minute,expected",
    [
        (9, 0, ("london", "new_york")),
        (8, 0, ("london", "new_york")),
        (11, 59, ("london", "new_york")),
        (12, 0, ("new_york",)),
        (16, 59, ("new_york",)),
        (17, 0, ()),
        (18, 59, ()),
        (19, 0, ("asian",)),
        (20, 0, ("asian",)),
        (2, 59, ("asian",)),
        (3, 0, ("london",)),
    ],
)
def test_london_ny_overlap_two_sessions(hour, minute, expected):
    assert sessions_of(ny(2026, 11, 4, hour, minute)) == expected


def test_sessions_follow_new_york_in_summer():
    assert sessions_of(ny(2026, 7, 15, 9, 0)) == ("london", "new_york")


def test_sessions_custom_table():
    custom = {
        "asian": ("20:00", "02:00"),
        "london": ("02:00", "11:00"),
        "new_york": ("07:00", "16:00"),
    }
    assert sessions_of(ny(2026, 11, 4, 19, 30), custom) == ()
    assert sessions_of(ny(2026, 11, 4, 7, 0), custom) == ("london", "new_york")


@pytest.mark.parametrize("bad", ["12:60", "00:75", "-0:30", "24:00", "7:00", "ab:cd"])
def test_sessions_reject_malformed_times(bad):
    with pytest.raises(ValueError, match="HH:MM"):
        sessions_of(ny(2026, 11, 4, 9, 0), {"asian": (bad, "03:00")})
