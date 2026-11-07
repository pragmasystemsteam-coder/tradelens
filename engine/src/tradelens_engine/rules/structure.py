"""Trend, break of structure and change of character (FR-SMC-03/04/05; DD 3.4).

One :class:`Structure` per pivot set (internal and external). Rules, as in the design:

* Trend (FR-SMC-03): while Neutral, after each new swing, if the last two highs and the last
  two lows make a higher high and a higher low and the latest low is still unbroken, the trend
  turns Bull with that low protected; mirror for Bear. Equal values keep it Neutral.
* BOS (FR-SMC-04, CD-15): close only (a wick is never a break), strictly beyond the level plus
  ``buf_m`` thousandths of ATR. Every unbroken level the close is beyond is consumed, so each
  level gives at most one break; older levels the close did not reach stay on the stack.
* CHoCH (FR-SMC-05): the first close beyond the protected swing against the trend. Never from
  Neutral: in Neutral, and for a non-protected level against the trend, levels are consumed
  silently so a stale break cannot fire once a trend starts.

Prices are integers; the buffer comparison cross-multiplies (``c * 10**6 > p * 10**6 + m*atr_k``).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Literal

from tradelens_engine.rules.swings import Swing
from tradelens_engine.types import Candle, Dir

Trend = Literal["neutral", "bull", "bear"]
BreakType = Literal["bos", "choch"]
HISTORY = 30  # confirmed highs and lows kept per structure (DD 3.2)
UNBROKEN_MAX = 60  # unbroken levels kept per side; the protected swing is never dropped
SCALE = 1_000_000  # price x 10**6 against m (thousandths) x atr_k (ATR x 1000)


@dataclass(frozen=True, slots=True)
class Structure:
    """Market structure for one pivot set (internal or external)."""

    trend: Trend = "neutral"
    highs: tuple[Swing, ...] = ()
    lows: tuple[Swing, ...] = ()
    unbroken_highs: tuple[Swing, ...] = ()
    unbroken_lows: tuple[Swing, ...] = ()
    protected_high: Swing | None = None
    protected_low: Swing | None = None
    protect_after: int | None = None  # bar of the last broken level (protected swing comes later)


@dataclass(frozen=True, slots=True)
class Break:
    """A BOS or CHoCH: ``origin_time`` is the broken swing's origin, ``confirm_time`` the close."""

    type: BreakType
    direction: Dir
    level: Swing
    origin_time: datetime
    confirm_time: datetime


def _lowest_after(lows: Iterable[Swing], bar: int) -> Swing | None:
    after = [s for s in lows if s.bar > bar]
    return min(after, key=lambda s: (s.price, s.bar)) if after else None


def _highest_after(highs: Iterable[Swing], bar: int) -> Swing | None:
    after = [s for s in highs if s.bar > bar]
    return max(after, key=lambda s: (s.price, -s.bar)) if after else None


def _start_trend(st: Structure) -> Structure:
    if st.trend != "neutral" or len(st.highs) < 2 or len(st.lows) < 2:  # noqa: PLR2004
        return st
    (h1, h2), (l1, l2) = st.highs[-2:], st.lows[-2:]
    if h2.price > h1.price and l2.price > l1.price and l2 in st.unbroken_lows:
        return replace(st, trend="bull", protected_low=l2, protected_high=None)
    if h2.price < h1.price and l2.price < l1.price and h2 in st.unbroken_highs:
        return replace(st, trend="bear", protected_high=h2, protected_low=None)
    return st


def _cap(levels: tuple[Swing, ...], keep: Swing | None) -> tuple[Swing, ...]:
    """Keep the newest UNBROKEN_MAX levels, plus the protected swing wherever it is."""
    if len(levels) <= UNBROKEN_MAX:
        return levels
    newest = levels[-UNBROKEN_MAX:]
    if keep is not None and keep in levels and keep not in newest:
        return (keep, *levels[-(UNBROKEN_MAX - 1) :])
    return newest


def add_swing(st: Structure, swing: Swing) -> Structure:
    """Record a newly confirmed swing; may start a trend or fill an empty protected swing.

    Implements FR-SMC-03 (trend start) and the "None until one exists" rule of
    ``pick_protected`` (DD 3.4).
    """
    if swing.kind == "high":
        st = replace(
            st,
            highs=(*st.highs, swing)[-HISTORY:],
            unbroken_highs=_cap((*st.unbroken_highs, swing), st.protected_high),
        )
        if st.trend == "bear" and st.protected_high is None and _after(st, swing):
            st = replace(st, protected_high=swing)
    else:
        st = replace(
            st,
            lows=(*st.lows, swing)[-HISTORY:],
            unbroken_lows=_cap((*st.unbroken_lows, swing), st.protected_low),
        )
        if st.trend == "bull" and st.protected_low is None and _after(st, swing):
            st = replace(st, protected_low=swing)
    return _start_trend(st)


def _after(st: Structure, swing: Swing) -> bool:
    return st.protect_after is None or swing.bar > st.protect_after


def _beyond(levels: tuple[Swing, ...], close: int, threshold: int, up: bool) -> tuple[Swing, ...]:
    if up:
        return tuple(s for s in levels if close * SCALE > s.price * SCALE + threshold)
    return tuple(s for s in levels if close * SCALE < s.price * SCALE - threshold)


def detect_breaks(
    st: Structure, candle: Candle, atr_k: int | None, buf_m: int
) -> tuple[Structure, list[Break]]:
    """Apply one closed candle to the structure (FR-SMC-04, FR-SMC-05).

    Args:
        st: Structure before the candle.
        candle: The candle that just closed.
        atr_k: ATR x1000, or None (then the buffer is 0).
        buf_m: ``bos_buffer_m`` in thousandths of ATR.

    Returns:
        The new structure and at most one break per direction.
    """
    threshold = buf_m * (atr_k or 0)
    events: list[Break] = []
    up = _beyond(st.unbroken_highs, candle.c, threshold, up=True)
    if up:
        st = replace(st, unbroken_highs=tuple(s for s in st.unbroken_highs if s not in up))
        top = max(up, key=lambda s: (s.price, s.bar))
        if st.trend == "bull":
            events.append(Break("bos", "bull", top, top.origin_time, candle.close_time))
            st = replace(st, protected_low=_lowest_after(st.unbroken_lows, top.bar),
                         protect_after=top.bar)  # fmt: skip
        elif st.trend == "bear" and (level := st.protected_high) is not None and level in up:
            events.append(Break("choch", "bull", level, level.origin_time, candle.close_time))
            st = replace(st, trend="bull", protected_high=None,
                         protected_low=_lowest_after(st.unbroken_lows, level.bar),
                         protect_after=level.bar)  # fmt: skip
    flipped = any(e.type == "choch" for e in events)
    down = _beyond(st.unbroken_lows, candle.c, threshold, up=False)
    if down:
        st = replace(st, unbroken_lows=tuple(s for s in st.unbroken_lows if s not in down))
        bottom = min(down, key=lambda s: (s.price, -s.bar))
        if flipped:
            pass  # one candle never changes character twice: crossed stale levels are consumed
        elif st.trend == "bear":
            events.append(Break("bos", "bear", bottom, bottom.origin_time, candle.close_time))
            st = replace(st, protected_high=_highest_after(st.unbroken_highs, bottom.bar),
                         protect_after=bottom.bar)  # fmt: skip
        elif st.trend == "bull" and (level := st.protected_low) is not None and level in down:
            events.append(Break("choch", "bear", level, level.origin_time, candle.close_time))
            st = replace(st, trend="bear", protected_low=None,
                         protected_high=_highest_after(st.unbroken_highs, level.bar),
                         protect_after=level.bar)  # fmt: skip
    return st, events
