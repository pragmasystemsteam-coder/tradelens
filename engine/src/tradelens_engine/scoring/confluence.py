"""C: confluence with the higher timeframes (DD 3.5, 3.6; FR-MTF-04, 06).

Four factors, maxima 40 + 30 + 20 + 10 = 100, from the context built as of the break close
(a forming higher-timeframe candle is never visible). The lower-timeframe confirmation is 0 at
creation and added later by re-evaluation. A context with fewer than 14 candles is not ready.
"""

from __future__ import annotations

from tradelens_engine.arith import le_atr
from tradelens_engine.context import TfContext
from tradelens_engine.scoring.model import Factor, ScoringConfig
from tradelens_engine.setups import SetupCandidate


def _ready(c: SetupCandidate) -> tuple[TfContext, ...]:
    if c.context is None:
        return ()
    return tuple(ctx for ctx in c.context.contexts if ctx.ready)


def _trend(c: SetupCandidate, w: ScoringConfig) -> Factor:
    contexts = () if c.context is None else c.context.contexts
    if not _ready(c):
        return Factor("htf_trend", "C", 0, w.trend_all, "not_ready")
    agree = tuple(ctx.timeframe for ctx in contexts if ctx.ready and ctx.trend == c.direction)
    others = tuple(ctx.timeframe for ctx in contexts if ctx.timeframe not in agree)
    args = (("agree", agree), ("others", others))
    if agree and len(agree) == len(contexts):
        return Factor("htf_trend", "C", w.trend_all, w.trend_all, "agree_all", args)
    if agree:
        return Factor("htf_trend", "C", w.trend_one, w.trend_all, "agree_one", args)
    return Factor("htf_trend", "C", 0, w.trend_all, "none", args)


def _zone(c: SetupCandidate, w: ScoringConfig) -> Factor:
    for ctx in _ready(c):
        for z in ctx.zones:
            if z.direction == c.direction and c.zone_low <= z.high and c.zone_high >= z.low:
                args = (("tf", ctx.timeframe), ("kind", z.kind))
                return Factor("htf_zone", "C", w.htf_zone, w.htf_zone, "inside", args)
    return Factor("htf_zone", "C", 0, w.htf_zone, "none")


def _conflict(c: SetupCandidate, w: ScoringConfig) -> Factor:
    ready = _ready(c)
    if not ready:
        return Factor("no_conflict", "C", 0, w.no_conflict, "not_ready")
    for ctx in ready:
        for z in ctx.zones:
            if z.direction == c.direction:
                continue
            gap = max(0, z.low - c.zone_high, c.zone_low - z.high)
            if le_atr(gap, w.conflict_distance_m, ctx.atr_k):
                args = (("tf", ctx.timeframe), ("kind", z.kind))
                return Factor("no_conflict", "C", 0, w.no_conflict, "conflict", args)
    return Factor("no_conflict", "C", w.no_conflict, w.no_conflict, "clear")


def c_factors(c: SetupCandidate, w: ScoringConfig) -> tuple[tuple[Factor, ...], bool]:
    """The four C factors at creation and the counter-trend flag.

    Returns:
        ``(factors, counter_trend)``; counter-trend means trend points 0 while at least one
        ready context trends the other way (FR-MTF-06).
    """
    trend = _trend(c, w)
    opposite = "bear" if c.direction == "bull" else "bull"
    counter = trend.points == 0 and any(ctx.trend == opposite for ctx in _ready(c))
    ltf = Factor("ltf_confirm", "C", 0, w.ltf_confirm, "zone_not_touched")
    return (trend, _zone(c, w), ltf, _conflict(c, w)), counter
