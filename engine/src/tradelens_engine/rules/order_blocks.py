"""Order blocks (FR-SMC-10; DD 3.4 "Order blocks").

On a bullish displacement the candidate is the last bearish candle (close < open) before the
move, searching back at most ``ob_lookback`` bars and not past the latest internal swing low;
mirror for bearish. It is dropped once a later close goes below its low (above its high for
bearish). It stays a provisional candidate until an internal BOS or CHoCH in the same direction
within ``disp_break_window`` candles of the move's end promotes it to a zone with the full
high-to-low range. ``pre_confirmation_touch``: a candle between the OB and the move, or between
the move and the break, overlapped it (the leg candles always overlap and are excluded; the
break candle is the confirmation itself and is excluded too).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from tradelens_engine.rules.displacement import Displacement
from tradelens_engine.types import Candle, Dir


@dataclass(frozen=True, slots=True)
class ObCandidate:
    """A provisional order block; ``detected_time`` is the displacement close (FR-ZONE-01)."""

    bar: int
    origin_time: datetime
    low: int
    high: int
    detected_time: datetime


@dataclass(frozen=True, slots=True)
class DispRecord:
    """A displacement that ended in the last ``disp_break_window`` bars, with its OB state."""

    disp: Displacement
    event_id: str
    candidate: ObCandidate | None
    ob_zone_id: str | None = None


def candle_at(window: Sequence[Candle], bar: int, j: int) -> Candle | None:
    """Candle of bar ``j`` when ``window[-1]`` is bar ``bar`` (None if outside the window)."""
    idx = len(window) - 1 - (bar - j)
    return window[idx] if 0 <= idx < len(window) else None


def closed_beyond(cand: ObCandidate, direction: Dir, close: int) -> bool:
    """True if ``close`` drops the candidate: below its low (bull) or above its high (bear)."""
    return close < cand.low if direction == "bull" else close > cand.high


def find_order_block(
    window: Sequence[Candle], bar: int, disp: Displacement, *, limit_bar: int | None, lookback: int
) -> ObCandidate | None:
    """The OB candidate of ``disp`` (None if there is none or it was already closed through).

    Args:
        window: Recent candles; ``window[-1]`` is bar ``bar``.
        bar: Current bar (the displacement's end).
        disp: The displacement.
        limit_bar: Bar of the latest internal swing low (bull) or high (bear); not searched past.
        lookback: ``ob_lookback``: bars searched before the move.
    """
    stop = disp.first_bar - lookback
    if limit_bar is not None:
        stop = max(stop, limit_bar)
    for j in range(disp.first_bar - 1, stop - 1, -1):
        c = candle_at(window, bar, j)
        if c is None:
            return None
        opposing = c.c < c.o if disp.direction == "bull" else c.c > c.o
        if not opposing:
            continue
        cand = ObCandidate(j, c.open_time, c.l, c.h, disp.confirm_time)
        for k in range(j + 1, bar + 1):
            later = candle_at(window, bar, k)
            if later is not None and closed_beyond(cand, disp.direction, later.c):
                return None
        return cand
    return None


def pre_confirmation_touch(
    window: Sequence[Candle], bar: int, cand: ObCandidate, disp: Displacement, break_bar: int
) -> bool:
    """True if a candle between the OB and the move, or the move and the break, overlapped it."""
    bars = (*range(cand.bar + 1, disp.first_bar), *range(disp.end_bar + 1, break_bar))
    for j in bars:
        c = candle_at(window, bar, j)
        if c is not None and c.l <= cand.high and c.h >= cand.low:
            return True
    return False
