"""Swing highs and lows (FR-SMC-01, FR-SMC-02; DD 3.4 "Swings").

A candidate bar ``k = t - R`` is a swing high when ``H[k] > max(H[k-L..k-1])`` (left side
strict) and ``H[k] >= max(H[k+1..t])`` (right side not strict); mirror for lows. So a plateau
of equal highs gives one swing, the first. ``origin_time`` is the open of bar ``k`` (where the
swing formed); ``confirm_time`` is the close of bar ``t`` (when it became knowable), so a
swing is never used before its right side has closed (no look-ahead).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from tradelens_engine.types import Candle

SwingKind = Literal["high", "low"]


@dataclass(frozen=True, slots=True)
class Swing:
    """A confirmed swing point; ``bar`` is the 1-based bar index of the swing candle."""

    kind: SwingKind
    price: int
    bar: int
    origin_time: datetime
    confirm_time: datetime


def confirm_swings(window: Sequence[Candle], last_bar: int, left: int, right: int) -> list[Swing]:
    """Swings confirmed by the close of the newest candle.

    Implements FR-SMC-01/02 (pivot L/R, left strict, right non-strict).

    Args:
        window: Recent candles, oldest first; the last one is bar ``last_bar``.
        last_bar: Bar index of ``window[-1]``.
        left: Bars required on the left (L).
        right: Bars required on the right (R).

    Returns:
        At most one high and one low, both for candidate bar ``last_bar - right``.
    """
    if left < 1 or right < 1 or len(window) < left + right + 1:
        return []
    k = len(window) - 1 - right
    cand, lefts, rights = window[k], window[k - left : k], window[k + 1 :]
    confirm_time = window[-1].close_time
    bar = last_bar - right
    out: list[Swing] = []
    if cand.h > max(c.h for c in lefts) and cand.h >= max(c.h for c in rights):
        out.append(Swing("high", cand.h, bar, cand.open_time, confirm_time))
    if cand.l < min(c.l for c in lefts) and cand.l <= min(c.l for c in rights):
        out.append(Swing("low", cand.l, bar, cand.open_time, confirm_time))
    return out
