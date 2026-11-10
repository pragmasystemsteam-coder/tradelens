"""Q: the quality of the setup on its own timeframe (DD 3.6; FR-MTF-03).

Six factors, maxima 25 + 20 + 20 + 15 + 15 + 5 = 100. Missing inputs (no OB, no opposing
level, no ATR) score 0 with a reason, never an error (FR-MTF-09).
"""

from __future__ import annotations

from tradelens_engine.arith import ge_atr
from tradelens_engine.scoring.model import Factor, ScoringConfig
from tradelens_engine.setups import SetupCandidate

ACTIVE_SESSIONS = ("london", "new_york")
MILLION = 1_000_000


def _break(c: SetupCandidate, w: ScoringConfig) -> Factor:
    args = (("level", c.break_level), ("candles", c.displacement_candles))
    if c.displacement_strong:
        return Factor("break", "Q", w.break_strong, w.break_strong, "strong", args)
    return Factor("break", "Q", w.break_minimal, w.break_strong, "minimal", args)


def _room(c: SetupCandidate, w: ScoringConfig) -> Factor:
    def factor(points: int, reason: str, *args: tuple[str, object]) -> Factor:
        return Factor("room", "Q", points, w.room_full, reason, tuple(args))

    if not c.atr_k:
        return factor(0, "no_atr")
    if c.opposing_level is None:
        return factor(0, "no_opposing_level")
    near = c.zone_high if c.direction == "bull" else c.zone_low
    dist = c.opposing_level - near if c.direction == "bull" else near - c.opposing_level
    args = (("level", c.opposing_level), ("multiple_k", max(dist, 0) * MILLION // c.atr_k))
    if ge_atr(dist, w.room_full_m, c.atr_k):
        return factor(w.room_full, "room_ge2", *args)
    if ge_atr(dist, w.room_part_m, c.atr_k):
        return factor(w.room_part, "room_ge1", *args)
    return factor(0, "room_lt1", *args)


def _spread_session(c: SetupCandidate, w: ScoringConfig, normal_spread: int) -> Factor:
    session = next((s for s in ACTIVE_SESSIONS if s in c.sessions), None)
    args = (("spread", c.spread), ("normal", normal_spread), ("session", session or ""))
    if c.spread > normal_spread:
        return Factor("spread_session", "Q", 0, w.spread_session, "wide_spread", args)
    if session is None:
        return Factor("spread_session", "Q", 0, w.spread_session, "off_session", args)
    return Factor("spread_session", "Q", w.spread_session, w.spread_session, "ok", args)


def q_factors(c: SetupCandidate, w: ScoringConfig, normal_spread: int) -> tuple[Factor, ...]:
    """The six Q factors of a candidate, in the order of DD 3.6.

    Args:
        c: The setup candidate.
        w: Weights.
        normal_spread: The instrument's normal spread in smallest units (``instruments``).

    Returns:
        Break, sweep, FVG, fresh OB, room to opposing liquidity, spread and session.
    """
    if c.ob_zone_id is None:
        ob = Factor("ob_fresh", "Q", 0, w.ob_fresh, "no_ob")
    elif c.ob_pre_touched:
        ob = Factor("ob_fresh", "Q", 0, w.ob_fresh, "ob_pre_touched")
    else:
        ob = Factor("ob_fresh", "Q", w.ob_fresh, w.ob_fresh, "ob_fresh")
    return (
        _break(c, w),
        Factor("sweep", "Q", w.sweep if c.sweep_event_id else 0, w.sweep,
               "sweep_found" if c.sweep_event_id else "no_sweep"),
        Factor("fvg", "Q", w.fvg if c.fvg_zone_id else 0, w.fvg,
               "fvg_found" if c.fvg_zone_id else "no_fvg"),
        ob,
        _room(c, w),
        _spread_session(c, w, normal_spread),
    )  # fmt: skip
