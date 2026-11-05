"""Integer arithmetic (Detailed Design 3.3, DD-5).

Units: price U = price x 10**price_scale; ``atr_k`` = ATR in U x 1000; multipliers ``m``
in thousandths (1.5 = 1500). Comparisons cross-multiply; nothing divides except the
documented half-up roundings.
"""

from __future__ import annotations

from dataclasses import dataclass

from tradelens_engine.types import Candle, require_int

SCORE_MAX = 100
PERMILLE = 1000


def ge_atr(x: int, m: int, atr_k: int | None) -> bool:
    """X >= (m / 1000) x ATR. False when ATR is missing or zero (reason 'no_atr')."""
    if not atr_k:
        return False
    return x * 1_000_000 >= m * atr_k


def le_atr(x: int, m: int, atr_k: int | None) -> bool:
    """X <= (m / 1000) x ATR. False when ATR is missing or zero."""
    if not atr_k:
        return False
    return x * 1_000_000 <= m * atr_k


def body_ratio_ok(body: int, rng: int, permille: int) -> bool:
    """Body / range >= permille / 1000; a zero range never qualifies."""
    return rng > 0 and body * 1000 >= permille * rng


def combined_score(q: int, c: int, q_permille: int = 600, c_permille: int = 400) -> int:
    """Combined rank = 0.6 Q + 0.4 C, rounded half up (never Python round())."""
    for name, value in (("q", q), ("c", c)):
        if not 0 <= require_int(name, value) <= SCORE_MAX:
            raise ValueError(f"{name} must be 0..100, got {value}")
    if q_permille + c_permille != PERMILLE:
        raise ValueError("score weights must sum to 1000 permille")
    return (q_permille * q + c_permille * c + 500) // 1000


@dataclass(frozen=True, slots=True)
class AtrState:
    """Wilder ATR state; ``atr_k`` stays None until ``period`` candles have been seen."""

    prev_close: int | None = None
    tr_count: int = 0
    tr_sum: int = 0
    atr_k: int | None = None


def atr_update(state: AtrState, candle: Candle, period: int = 14) -> AtrState:
    """Wilder ATR(period), current candle included, SMA seed, rounded half up."""
    h, l, prev = candle.h, candle.l, state.prev_close  # noqa: E741
    tr = h - l if prev is None else max(h - l, abs(h - prev), abs(l - prev))
    n = state.tr_count + 1
    half = period // 2
    if n < period:
        return AtrState(candle.c, n, state.tr_sum + tr, None)
    if n == period:
        total = state.tr_sum + tr
        return AtrState(candle.c, n, total, (total * 1000 + half) // period)
    if state.atr_k is None:
        raise ValueError("AtrState has tr_count >= period but no atr_k")
    atr_k = (state.atr_k * (period - 1) + tr * 1000 + half) // period
    return AtrState(candle.c, n, state.tr_sum, atr_k)
