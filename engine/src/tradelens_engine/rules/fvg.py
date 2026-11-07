"""Fair value gaps (FR-SMC-06; DD 3.4 "FVG").

With ``a`` = bar t-2 and ``c`` = bar t: bullish when ``c.l > a.h`` (zone ``[a.h, c.l]``),
bearish when ``c.h < a.l`` (zone ``[c.h, a.l]``). Equal values are not a gap. With
``fvg_min_m > 0`` a gap smaller than that multiple of ATR is not created, and without an ATR
yet it is not created either (the size cannot be checked).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from tradelens_engine.arith import ge_atr
from tradelens_engine.types import Candle, Dir


@dataclass(frozen=True, slots=True)
class Fvg:
    """A fair value gap; ``bar`` is the bar index of the third candle (the confirming close)."""

    direction: Dir
    low: int
    high: int
    origin_time: datetime
    confirm_time: datetime
    bar: int


def detect_fvg(
    a: Candle, b: Candle, c: Candle, bar: int, atr_k: int | None, fvg_min_m: int
) -> Fvg | None:
    """Return the FVG formed by three consecutive candles, if any.

    Implements FR-SMC-06 (strict three-candle gap, optional ATR minimum).

    Args:
        a: Bar t-2.
        b: Bar t-1 (the displacement candle; its range does not matter).
        c: Bar t.
        bar: Bar index of ``c``.
        atr_k: ATR x1000 as of bar t, or None before 14 candles.
        fvg_min_m: Minimum size in thousandths of ATR; 0 = no minimum.

    Returns:
        The gap, or None.
    """
    del b  # the middle candle is part of the pattern but not of the test
    if c.l > a.h:
        gap = Fvg("bull", a.h, c.l, a.open_time, c.close_time, bar)
    elif c.h < a.l:
        gap = Fvg("bear", c.h, a.l, a.open_time, c.close_time, bar)
    else:
        return None
    if fvg_min_m > 0 and not ge_atr(gap.high - gap.low, fvg_min_m, atr_k):
        return None
    return gap
