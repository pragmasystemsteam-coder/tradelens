"""Build higher-timeframe candles from lower ones (CR-004 D2-1 and D2-3, FR-DATA-04).

4H and 1D come from 1H on the 17:00 New York boundary; the provider's own daily bars are not
used. In development the live 15m and 1h candles come from 5m. A bucket is built only once it
has closed and every candle the calendar expects inside it is stored; otherwise it waits (the
missing candle is a gap of the source series, which the ingest job backfills).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime

from tradelens.modules.market_data.calendar import Calendar, bucket_open, expected_open_times
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
