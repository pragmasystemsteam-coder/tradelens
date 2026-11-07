"""Trading calendars: which candles must exist, candle buckets and gaps (FR-DATA-04, FR-DATA-09).

Calendar times are New York wall-clock times (config/calendars.json, DD 6.5). All maths runs on
UTC instants converted with ``ZoneInfo``, so daylight saving needs no special code. Markets are
closed when New York changes clocks (Sunday 02:00), so no trading day spans a DST switch.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from tradelens.modules.market_data.candles import timeframe_delta

NY = ZoneInfo("America/New_York")
DAY_START_HOUR = 17  # FR-DATA-04: 4H and 1D candles are aligned to 17:00 New York
MINUTES_PER_DAY = 1440
MINUTES_PER_HOUR = 60
BREAK_DAYS = frozenset({1, 2, 3, 4})  # daily break Monday to Thursday (dow 0 = Sunday)
NY_ALIGNED = frozenset({"4h", "1d"})
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
ONE_HOUR = timedelta(hours=1)
ONE_DAY = timedelta(days=1)
MIN_FOR_GAP = 2  # a gap needs a stored candle on each side


def _minutes(hhmm: str) -> int:
    hours, minutes = hhmm.split(":")
    return int(hours) * MINUTES_PER_HOUR + int(minutes)


def _local_instant(value: str, tz: ZoneInfo) -> datetime:
    parsed = datetime.fromisoformat(value)
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=tz)).astimezone(UTC)


@dataclass(frozen=True, slots=True)
class Calendar:
    """A trading calendar (``trading_calendars`` row) in minutes of the New York week."""

    code: str
    tz: ZoneInfo
    week_open: int  # minute of the week, Sunday 00:00 = 0
    week_close: int
    break_start: int | None  # minute of the day
    break_end: int | None
    closures: tuple[tuple[datetime, datetime], ...]

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> Calendar:
        """Build from a config/calendars.json item or a ``trading_calendars`` row."""
        tz = ZoneInfo(str(row["tz"]))
        start, end = row["daily_break_start"], row["daily_break_end"]
        closures = tuple(
            (_local_instant(str(c["from"]), tz), _local_instant(str(c["to"]), tz))
            for c in row.get("closures") or ()
        )
        open_dow, close_dow = int(row["week_open_dow"]), int(row["week_close_dow"])
        return cls(
            code=str(row["code"]),
            tz=tz,
            week_open=open_dow * MINUTES_PER_DAY + _minutes(str(row["week_open_time"])),
            week_close=close_dow * MINUTES_PER_DAY + _minutes(str(row["week_close_time"])),
            break_start=None if start is None else _minutes(str(start)),
            break_end=None if end is None else _minutes(str(end)),
            closures=closures,
        )


def is_open(cal: Calendar, t: datetime) -> bool:
    """True when the market of ``cal`` is open at instant ``t``."""
    local = t.astimezone(cal.tz)
    dow = (local.weekday() + 1) % 7  # Python counts Monday as 0; calendars count Sunday as 0
    minute_of_day = local.hour * MINUTES_PER_HOUR + local.minute
    minute_of_week = dow * MINUTES_PER_DAY + minute_of_day
    if not cal.week_open <= minute_of_week < cal.week_close:
        return False
    if (
        cal.break_start is not None
        and cal.break_end is not None
        and dow in BREAK_DAYS
        and cal.break_start <= minute_of_day < cal.break_end
    ):
        return False
    return not any(start <= t < end for start, end in cal.closures)


def _day_start(local_date: date) -> datetime:
    return datetime(local_date.year, local_date.month, local_date.day, DAY_START_HOUR, tzinfo=NY)


def bucket_open(timeframe: str, t: datetime) -> datetime:
    """Open time of the ``timeframe`` candle containing ``t``.

    5m, 15m and 1h are aligned to UTC; 4h and 1d to the 17:00 New York trading day.
    """
    step = timeframe_delta(timeframe)
    if timeframe not in NY_ALIGNED:
        return t - (t - EPOCH) % step
    local = t.astimezone(NY)
    start = _day_start((local - timedelta(hours=DAY_START_HOUR)).date())
    elapsed = local.replace(tzinfo=None) - start.replace(tzinfo=None)  # wall-clock difference
    return (start + (elapsed // step) * step).astimezone(UTC)


def _bucket_starts(timeframe: str, start: datetime, end: datetime) -> Iterator[datetime]:
    """Every candle open time of ``timeframe`` in ``[start, end)``, open market or not."""
    step = timeframe_delta(timeframe)
    if timeframe not in NY_ALIGNED:
        t = bucket_open(timeframe, start)
        while t < end:
            if t >= start:
                yield t
            t += step
        return
    day = (start.astimezone(NY) - timedelta(hours=DAY_START_HOUR)).date()
    while _day_start(day).astimezone(UTC) < end:
        wall = _day_start(day)
        for k in range(ONE_DAY // step):
            t = (wall + k * step).astimezone(UTC)  # wall-clock steps inside the trading day
            if start <= t < end:
                yield t
        day += ONE_DAY


def is_expected(cal: Calendar, timeframe: str, open_time: datetime) -> bool:
    """True when a candle opening at ``open_time`` must exist.

    An intraday candle must exist when the market is open at its open time. A 4h or 1d candle
    exists when any hour inside it is open, so the metal 17:00 4H bucket (break 17-18) exists.
    """
    if timeframe not in NY_ALIGNED:
        return is_open(cal, open_time)
    # Walk New York wall-clock hours: the Saturday 1d bucket before a DST switch is 23 or 25
    # real hours long, and must not reach into the Sunday open.
    wall = open_time.astimezone(NY).replace(tzinfo=None)
    hours = timeframe_delta(timeframe) // ONE_HOUR
    return any(is_open(cal, (wall + k * ONE_HOUR).replace(tzinfo=NY)) for k in range(hours))


def expected_open_times(
    cal: Calendar, timeframe: str, start: datetime, end: datetime
) -> list[datetime]:
    """Open times of every candle that must exist in ``[start, end)``."""
    return [t for t in _bucket_starts(timeframe, start, end) if is_expected(cal, timeframe, t)]


def find_gaps(
    cal: Calendar, timeframe: str, stored: Sequence[datetime]
) -> list[tuple[datetime, datetime]]:
    """Missing candles between the first and the last stored one (DD 7.2 Calendars).

    Only candles with a later stored candle count, so a candle that is merely not complete
    yet is never a gap.

    Returns:
        ``(gap_from, gap_to)`` per run of consecutive missing candles: the first missing open
        time and the close of the last missing candle (exclusive end, as ``data_gaps`` stores).
    """
    if len(stored) < MIN_FOR_GAP:
        return []
    have = set(stored)
    step = timeframe_delta(timeframe)
    gaps: list[tuple[datetime, datetime]] = []
    run: list[datetime] = []
    for t in expected_open_times(cal, timeframe, min(have), max(have)):
        if t in have:
            if run:
                gaps.append((run[0], run[-1] + step))
                run = []
        else:
            run.append(t)
    if run:
        gaps.append((run[0], run[-1] + step))
    return gaps
