"""Build higher-timeframe candles from lower ones (CR-004 D2-1 and D2-3, FR-DATA-04).

4H and 1D come from 1H on the 17:00 New York boundary; the provider's own daily bars are not
used. In development the live 15m and 1h candles come from 5m. A bucket is built only once it
has closed and every candle the calendar expects inside it is stored; otherwise it waits (the
missing candle is a gap of the source series, which the ingest job backfills).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from tradelens.modules.market_data.calendar import (
    NY,
    NY_ALIGNED,
    Calendar,
    bucket_open,
    expected_open_times,
)
from tradelens.modules.market_data.candles import StoredCandle, timeframe_delta


def _merge(target_tf: str, open_time: datetime, bars: Sequence[StoredCandle]) -> StoredCandle:
    first, last = bars[0], bars[-1]
    return StoredCandle(
        instrument=first.instrument,
        timeframe=target_tf,
        open_time=open_time,
        o=first.o,
        h=max(b.h for b in bars),
        l=min(b.l for b in bars),
        c=last.c,
        bid_o=first.bid_o,
        bid_h=max(b.bid_h for b in bars),
        bid_l=min(b.bid_l for b in bars),
        bid_c=last.bid_c,
        ask_o=first.ask_o,
        ask_h=max(b.ask_h for b in bars),
        ask_l=min(b.ask_l for b in bars),
        ask_c=last.ask_c,
        source=first.source,
        tick_volume=sum(b.tick_volume for b in bars),
    )


def aggregate(
    cal: Calendar,
    source_tf: str,
    target_tf: str,
    bars: Sequence[StoredCandle],
    now: datetime,
    after: datetime | None = None,
) -> list[StoredCandle]:
    """Merge ``source_tf`` candles of one instrument into complete ``target_tf`` candles.

    Args:
        cal: The instrument's trading calendar.
        source_tf: Timeframe of ``bars``.
        target_tf: Timeframe to build (a whole multiple of ``source_tf``).
        bars: Stored source candles of one instrument.
        now: Current UTC time; a bucket is built only once ``now`` reaches its close.
        after: Build only buckets that open strictly after this time (already stored ones).

    Returns:
        New target candles in ascending open time.

    Raises:
        ValueError: If ``target_tf`` is not a multiple of ``source_tf``.
    """
    if timeframe_delta(target_tf) % timeframe_delta(source_tf):
        raise ValueError(f"{target_tf} is not a multiple of {source_tf}")
    step = timeframe_delta(target_tf)
    buckets: dict[datetime, list[StoredCandle]] = defaultdict(list)
    for bar in sorted(bars, key=lambda b: b.open_time):
        buckets[bucket_open(target_tf, bar.open_time)].append(bar)
    out: list[StoredCandle] = []
    for open_time in sorted(buckets):
        close_time = open_time + step
        if (after is not None and open_time <= after) or close_time > now:
            continue
        members = buckets[open_time]
        present = {b.open_time for b in members}
        expected = expected_open_times(cal, source_tf, open_time, close_time)
        if expected and set(expected) <= present:
            out.append(_merge(target_tf, open_time, members))
    return out


@dataclass(frozen=True, slots=True)
class FormingCandle:
    """The current, unfinished candle of a timeframe: shown on charts, never stored or scored."""

    timeframe: str
    open_time: datetime
    o: int
    h: int
    l: int  # noqa: E741 - OHLC naming used across the code base
    c: int
    closes_at: datetime


def bucket_close(timeframe: str, open_time: datetime) -> datetime:
    """Close time of the ``timeframe`` candle opening at ``open_time``.

    4h and 1d follow New York wall-clock time, so a trading day is 23 or 25 hours long in the
    weeks clocks change; the others are fixed lengths in UTC.
    """
    step = timeframe_delta(timeframe)
    if timeframe not in NY_ALIGNED:
        return open_time + step
    wall = open_time.astimezone(NY).replace(tzinfo=None) + step
    return wall.replace(tzinfo=NY).astimezone(UTC)


def forming_candle(
    target_tf: str,
    bars_5m: Sequence[StoredCandle],
    last_closed: datetime | None,
    now: datetime,
) -> FormingCandle | None:
    """The ``target_tf`` candle open at ``now``, built from the finished 5m candles inside it.

    Display only (charts): the engine, setups, scores and alerts use finished candles only.

    Args:
        target_tf: 15m, 1h, 4h or 1d (5m has no forming candle: no data inside 5 minutes).
        bars_5m: Recent stored 5m candles of one instrument.
        last_closed: Open time of the newest finished ``target_tf`` candle, if any.
        now: Current UTC time.

    Returns:
        The forming candle, or None when the period has no finished 5m candle yet or its
        finished candle is already stored.
    """
    if target_tf == "5m":
        return None
    open_time = bucket_open(target_tf, now)
    if last_closed is not None and last_closed >= open_time:
        return None
    members = sorted(
        (b for b in bars_5m
         if b.close_time <= now and bucket_open(target_tf, b.open_time) == open_time),
        key=lambda b: b.open_time,
    )  # fmt: skip
    if not members:
        return None
    m = _merge(target_tf, open_time, members)
    return FormingCandle(target_tf, open_time, m.o, m.h, m.l, m.c,
                         bucket_close(target_tf, open_time))  # fmt: skip
