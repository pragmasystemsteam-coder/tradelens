"""Displacement (FR-SMC-09; DD 3.4 "Displacement").

Single candle: range > 0, body >= ``single_m`` x ATR and ``body * 1000 >= 650 * range``.
Otherwise 2 or 3 same-colour candles whose net move (last close - first open) is at least
``multi_m`` x ATR. At most one per candle: single beats 2 beats 3. ``strong`` = it also meets
the strong table for its kind. A zero-range candle or a missing/zero ATR gives none.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from tradelens_engine.arith import body_ratio_ok, ge_atr
from tradelens_engine.types import Candle, Dir

MAX_CANDLES = 3


@dataclass(frozen=True, slots=True)
class Displacement:
    """Leg of bars ``first_bar..end_bar``: origin = first open, confirm = last close."""

    direction: Dir
    first_bar: int
    end_bar: int
    origin_time: datetime
    confirm_time: datetime
    candles: int
    strong: bool


def _colour(c: Candle) -> Dir | None:
    if c.c > c.o:
        return "bull"
    if c.c < c.o:
        return "bear"
    return None


def _single_ok(c: Candle, m: int, atr_k: int, body_permille: int) -> bool:
    body, rng = abs(c.c - c.o), c.h - c.l
    return rng > 0 and ge_atr(body, m, atr_k) and body_ratio_ok(body, rng, body_permille)


def detect_displacement(
    recent: Sequence[Candle],
    bar: int,
    atr_k: int | None,
    *,
    thresholds: Mapping[str, int],
    strong: Mapping[str, int],
    body_permille: int,
) -> Displacement | None:
    """The displacement ending at the newest candle, if any.

    Args:
        recent: The last candles, oldest first (at least the newest; up to 3 are used).
        bar: Bar index of ``recent[-1]``.
        atr_k: ATR x1000 as of this bar, or None.
        thresholds: ``{"single_m", "multi_m"}`` of the active strength setting.
        strong: The strong table (decides ``strong``).
        body_permille: Minimum body/range for a single candle (650).

    Returns:
        The displacement or None.
    """
    if not atr_k or not recent:
        return None
    last = recent[-1]
    direction = _colour(last)
    if direction is None:
        return None
    if _single_ok(last, thresholds["single_m"], atr_k, body_permille):
        is_strong = _single_ok(last, strong["single_m"], atr_k, body_permille)
        return Displacement(direction, bar, bar, last.open_time, last.close_time, 1, is_strong)
    for n in range(2, MAX_CANDLES + 1):
        if len(recent) < n:
            break
        leg = recent[-n:]
        if any(_colour(c) != direction for c in leg):
            break  # a longer leg would contain the same mixed colours
        net = abs(leg[-1].c - leg[0].o)
        if ge_atr(net, thresholds["multi_m"], atr_k):
            return Displacement(
                direction, bar - n + 1, bar, leg[0].open_time, last.close_time, n,
                ge_atr(net, strong["multi_m"], atr_k),
            )  # fmt: skip
    return None
