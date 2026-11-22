"""Current candidates for the analysis panel (CR-006). Display only.

A candidate is never stored, listed in the scanner ranking or alerted. It shows, per direction,
how the latest internal break would score under the same rules, and which gates of DD 3.6 it
misses (the reason no setup exists). Approved rules (CR-006):

1. The break is the latest internal BOS or CHoCH in the last ``LOOKBACK_BARS`` candles that did
   not already produce a setup.
2. Q and C factors use the normal weights; a missed gate (no displacement within
   ``disp_break_window`` candles, or no OB/FVG in the move) is marked, not hidden.
3. With no OB/FVG in the move, the nearest open same-direction OB or FVG within 1 x ATR of the
   break level is the "nearby" zone (used for room and invalidation, not for OB/FVG points).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from tradelens_engine.arith import le_atr
from tradelens_engine.context import HigherTfContext
from tradelens_engine.rules.lifecycle import ACTIVE_STATES
from tradelens_engine.scoring.confluence import c_factors
from tradelens_engine.scoring.model import Factor, ScoringConfig
from tradelens_engine.scoring.quality import q_factors
from tradelens_engine.scoring.rank import combined, totals
from tradelens_engine.setups import SetupCandidate

LOOKBACK_BARS = 50
NEARBY_ATR_M = 1000  # 1 x ATR, in thousandths
BREAKS = frozenset({"bos", "choch"})
OPEN_STATES = ACTIVE_STATES - {"filled"}


@dataclass(frozen=True, slots=True)
class EventIn:
    """A stored market event (``market_events``)."""

    id: str
    type: str
    structure: str | None
    direction: str | None
    level: int | None
    origin_time: datetime
    confirm_time: datetime
    strong: bool = False
    candles: int = 0


@dataclass(frozen=True, slots=True)
class ZoneIn:
    """A stored OB or FVG zone with its current state."""

    id: str
    kind: str
    direction: str
    low: int
    high: int
    state: str
    origin_time: datetime
    confirm_time: datetime
    pre_touch: bool = False


@dataclass(frozen=True, slots=True)
class LevelIn:
    """An active liquidity level: ``side`` is ``buy`` (above price) or ``sell`` (below)."""

    price: int
    side: str


@dataclass(frozen=True, slots=True)
class Check:
    """A setup gate of DD 3.6: ``break``, ``displacement`` or ``zone_in_move``."""

    code: str
    met: bool


@dataclass(frozen=True, slots=True)
class CandidateView:
    """How the latest break would score; labelled "Candidate, not a setup" everywhere."""

    direction: str
    break_event: EventIn
    displacement: EventIn | None
    sweep: EventIn | None
    zone: ZoneIn | None
    zone_nearby: bool
    checks: tuple[Check, ...]
    patterns: tuple[str, ...]
    factors: tuple[Factor, ...]
    q: int
    c: int
    combined: int
    counter_trend: bool


def _latest(items: Sequence[EventIn]) -> EventIn | None:
    return max(items, key=lambda e: e.confirm_time) if items else None


def _opposing(levels: Sequence[LevelIn], direction: str, low: int, high: int) -> int | None:
    if direction == "bull":
        above = [lv.price for lv in levels if lv.side == "buy" and lv.price > high]
        return min(above) if above else None
    below = [lv.price for lv in levels if lv.side == "sell" and lv.price < low]
    return max(below) if below else None


def _nearby(
    zones: Sequence[ZoneIn], direction: str, level: int | None, atr_k: int | None
) -> ZoneIn | None:
    if level is None:
        return None
    best: tuple[int, ZoneIn] | None = None
    for z in zones:
        if z.direction != direction or z.kind not in ("ob", "fvg") or z.state not in OPEN_STATES:
            continue
        dist = 0 if z.low <= level <= z.high else min(abs(level - z.low), abs(level - z.high))
        if le_atr(dist, NEARBY_ATR_M, atr_k) and (best is None or dist < best[0]):
            best = (dist, z)
    return best[1] if best else None


def current_candidates(
    *,
    instrument: str,
    timeframe: str,
    profile: str,
    settings_hash: str,
    rule_version: str,
    now: datetime,
    tf_seconds: int,
    events: Sequence[EventIn],
    zones: Sequence[ZoneIn],
    levels: Sequence[LevelIn],
    atr_k: int | None,
    context: HigherTfContext | None,
    setup_break_ids: frozenset[str],
    sessions: tuple[str, ...],
    spread: int,
    constants: Mapping[str, Any],
    weights: ScoringConfig,
    normal_spread: int,
) -> list[CandidateView]:
    """One candidate per direction at most (bull first), from stored engine output.

    Returns:
        Candidates whose break is recent and has no setup; empty when there is none.
    """
    tf = timedelta(seconds=tf_seconds)
    since = now - LOOKBACK_BARS * tf
    disp_window = int(constants["disp_break_window"]) * tf
    sweep_window = int(constants["sweep_window_bars"]) * tf
    out: list[CandidateView] = []
    for direction in ("bull", "bear"):
        brk = _latest([e for e in events
                       if e.type in BREAKS and e.structure == "internal"
                       and e.direction == direction and e.confirm_time > since
                       and e.id not in setup_break_ids])  # fmt: skip
        if brk is None:
            continue
        lo_disp, lo_sweep = brk.confirm_time - disp_window, brk.confirm_time - sweep_window
        disp = _latest([e for e in events
                        if e.type == "displacement" and e.direction == direction
                        and lo_disp <= e.confirm_time <= brk.confirm_time])  # fmt: skip
        sweep = _latest([e for e in events
                         if e.type == "sweep" and e.direction == direction
                         and lo_sweep <= e.confirm_time <= brk.confirm_time])  # fmt: skip
        in_move = [z for z in zones
                   if disp is not None and z.direction == direction and z.kind in ("ob", "fvg")
                   and z.origin_time >= disp.origin_time
                   and z.confirm_time <= brk.confirm_time]  # fmt: skip
        obs = [z for z in in_move if z.kind == "ob"]
        fvgs = [z for z in in_move if z.kind == "fvg"]
        ob = max(obs, key=lambda z: z.confirm_time) if obs else None
        fvg = max(fvgs, key=lambda z: z.confirm_time) if fvgs else None
        zone = ob or fvg
        nearby = False
        if zone is None:
            zone = _nearby(zones, direction, brk.level, atr_k)
            nearby = zone is not None
        level = brk.level if brk.level is not None else 0
        low, high = (zone.low, zone.high) if zone else (level, level)
        patterns = (brk.type, *(("displacement",) if disp else ()), *(("sweep",) if sweep else ()),
                    *(("fvg",) if fvg else ()), *(("ob",) if ob else ()))  # fmt: skip
        cand = SetupCandidate(
            id=f"candidate-{brk.id}"[:32], instrument=instrument, timeframe=timeframe,
            profile=profile, direction=direction, break_event_id=brk.id, break_type=brk.type,
            patterns=patterns, sessions=sessions, spread=spread, atr_k=atr_k,
            displacement_event_id=disp.id if disp else "",
            displacement_strong=bool(disp and disp.strong),
            sweep_event_id=sweep.id if sweep else None, ob_zone_id=ob.id if ob else None,
            fvg_zone_id=fvg.id if fvg else None, ob_pre_touched=bool(ob and ob.pre_touch),
            invalidation=low if direction == "bull" else high,
            opposing_level=_opposing(levels, direction, low, high),
            origin_time=zone.origin_time if zone else brk.origin_time,
            confirm_time=brk.confirm_time, settings_hash=settings_hash,
            rule_version=rule_version, context=context, zone_low=low, zone_high=high,
            break_level=level, displacement_candles=disp.candles if disp else 0,
        )  # fmt: skip
        cf, counter = c_factors(cand, weights)
        factors = (*q_factors(cand, weights, normal_spread), *cf)
        q, c = totals(factors)
        out.append(CandidateView(
            direction=direction, break_event=brk, displacement=disp, sweep=sweep, zone=zone,
            zone_nearby=nearby,
            checks=(Check("break", True), Check("displacement", disp is not None),
                    Check("zone_in_move", bool(in_move))),
            patterns=patterns, factors=factors, q=q, c=c, combined=combined(q, c, weights),
            counter_trend=counter,
        ))  # fmt: skip
    return out
