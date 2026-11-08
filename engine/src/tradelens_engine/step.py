"""``step``: apply one closed candle to a series (DD 3.1, 3.4; FR-SMC-01..10, FR-ZONE, FR-SCAN-01).

Order inside a step (DD 3.4): (1) order check, (2) ATR, (3) day, week and session rollover,
(4) confirm swings, (5) trend start and structure breaks, (6) FVG, (7) sweeps and breakouts,
then register new levels, (8) displacement, OB promotion and setup candidates, (9) lifecycle
of zones that existed before this candle, (10) expiry. Anything created in this candle is not
swept or advanced in the same candle. Every output carries ``confirm_time`` = this candle's
close (or, for an OB's ``detected`` transition, the earlier displacement close), so nothing
is known before the candle that revealed it (no look-ahead). IDs are deterministic (DD 3.8).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from tradelens_engine.arith import atr_update
from tradelens_engine.context import PROFILE_BY_TF, HigherTfContext
from tradelens_engine.events import Event, EventType, SeriesKey, StructureName, Zone
from tradelens_engine.ids import setup_id
from tradelens_engine.rules.displacement import detect_displacement
from tradelens_engine.rules.fvg import Fvg, detect_fvg
from tradelens_engine.rules.lifecycle import ACTIVE_STATES, ZoneState, advance_zone, expire_zone
from tradelens_engine.rules.liquidity import (
    Level,
    LevelChange,
    check_levels,
    expire_levels,
    register_levels,
    roll_boxes,
)
from tradelens_engine.rules.order_blocks import (
    DispRecord,
    ObCandidate,
    closed_beyond,
    find_order_block,
    pre_confirmation_touch,
)
from tradelens_engine.rules.structure import Structure, add_swing, detect_breaks
from tradelens_engine.rules.swings import Swing, confirm_swings
from tradelens_engine.series import RECENT_FVGS, WINDOW, SeriesState, SweepRec
from tradelens_engine.settings import Settings
from tradelens_engine.setups import SetupCandidate
from tradelens_engine.timekeys import sessions_of
from tradelens_engine.types import Candle

FVG_BARS = 3
Transition = tuple[str, str, datetime]


class OutOfOrderCandle(ValueError):  # noqa: N818 - name fixed by the design (DD 3.4)
    """A candle whose open time is not after the previous one; the engine never skips."""


@dataclass(frozen=True, slots=True)
class StepOutput:
    """What one candle produced, in emission order."""

    events: tuple[Event, ...] = ()
    new_zones: tuple[Zone, ...] = ()
    zone_transitions: tuple[Transition, ...] = ()
    level_changes: tuple[LevelChange, ...] = ()
    setup_candidates: tuple[SetupCandidate, ...] = ()


@dataclass(slots=True)
class _Out:
    events: list[Event] = field(default_factory=list)
    zones: list[Zone] = field(default_factory=list)
    transitions: list[Transition] = field(default_factory=list)
    levels: list[LevelChange] = field(default_factory=list)
    setups: list[SetupCandidate] = field(default_factory=list)

    def freeze(self) -> StepOutput:
        return StepOutput(tuple(self.events), tuple(self.zones), tuple(self.transitions),
                          tuple(self.levels), tuple(self.setups))  # fmt: skip


@dataclass(frozen=True, slots=True)
class _Bar:
    """Per-candle inputs shared by the helpers below."""

    key: SeriesKey
    cfg: Settings
    candle: Candle
    bar: int
    atr_k: int | None
    window: tuple[Candle, ...]

    def const(self, name: str) -> Any:  # noqa: ANN401 - constants are typed JSON
        return self.cfg.constants[name]


def _structure_step(
    b: _Bar, name: StructureName, st: Structure, swings: list[Swing], out: _Out
) -> tuple[Structure, list[Event]]:
    for swing in swings:
        st = add_swing(st, swing)
        kind: EventType = "swing_high" if swing.kind == "high" else "swing_low"
        out.events.append(
            b.key.event(kind, name, None, swing.price, swing.origin_time, swing.confirm_time)
        )
    st, breaks = detect_breaks(st, b.candle, b.atr_k, int(b.const("bos_buffer_m")))
    events = [
        b.key.event(x.type, name, x.direction, x.level.price, x.origin_time, x.confirm_time)
        for x in breaks
    ]
    out.events.extend(events)
    return st, events


def _fvg_step(
    b: _Bar, recent: tuple[Fvg, ...], out: _Out
) -> tuple[tuple[Fvg, ...], list[ZoneState]]:
    if len(b.window) < FVG_BARS:
        return recent, []
    w = b.window
    gap = detect_fvg(w[-3], w[-2], w[-1], b.bar, b.atr_k, b.cfg.fvg_min_m)
    if gap is None:
        return recent, []
    zid = b.key.zone_id("fvg", gap.direction, gap.origin_time, gap.low, gap.high)
    k = b.key
    zone = Zone(zid, "fvg", k.instrument, k.timeframe, gap.direction, gap.low, gap.high,
                gap.origin_time, gap.confirm_time, k.settings_hash, k.rule_version)  # fmt: skip
    out.zones.append(zone)
    # FR-ZONE-01: an FVG is detected and confirmed at the same close.
    out.transitions += [(zid, "detected", gap.confirm_time), (zid, "confirmed", gap.confirm_time)]
    return (*recent, gap)[-RECENT_FVGS:], [ZoneState(zone, "confirmed", gap.confirm_time, b.bar)]


def _displacement_step(
    b: _Bar, records: tuple[DispRecord, ...], internal: Structure, out: _Out
) -> list[DispRecord]:
    """Prune old displacements, drop closed-through OB candidates, detect this candle's move."""
    window_n = int(b.const("disp_break_window"))
    kept = []
    for rec in records:
        if b.bar - rec.disp.end_bar > window_n:
            continue
        cand = rec.candidate
        if cand is not None and closed_beyond(cand, rec.disp.direction, b.candle.c):
            rec = replace(rec, candidate=None)
        kept.append(rec)
    table = b.const("displacement")
    disp = detect_displacement(
        b.window[-3:], b.bar, b.atr_k, thresholds=table[b.cfg.displacement],
        strong=table["strong"], body_permille=int(b.const("body_ratio_permille")),
    )  # fmt: skip
    if disp is None:
        return kept
    event = b.key.event("displacement", None, disp.direction, None, disp.origin_time,
                        disp.confirm_time,
                        details=(("candles", disp.candles), ("strong", disp.strong)))  # fmt: skip
    out.events.append(event)
    swings = internal.lows if disp.direction == "bull" else internal.highs
    limit = swings[-1].bar if swings else None
    cand = find_order_block(b.window, b.bar, disp, limit_bar=limit,
                            lookback=int(b.const("ob_lookback")))  # fmt: skip
    return [*kept, DispRecord(disp, event.id, cand)]


def _promote(
    b: _Bar, rec: DispRecord, cand: ObCandidate, brk: Event, out: _Out
) -> tuple[DispRecord, ZoneState]:
    direction = rec.disp.direction
    zid = b.key.zone_id("ob", direction, cand.origin_time, cand.low, cand.high)
    touched = pre_confirmation_touch(b.window, b.bar, cand, rec.disp, b.bar)
    zone = Zone(zid, "ob", b.key.instrument, b.key.timeframe, direction, cand.low, cand.high,
                cand.origin_time, b.candle.close_time, b.key.settings_hash, b.key.rule_version,
                touched, brk.id)  # fmt: skip
    out.zones.append(zone)
    # The detected state lives in the candidate until now (the transition FK needs the zone).
    out.transitions += [(zid, "detected", cand.detected_time),
                        (zid, "confirmed", b.candle.close_time)]  # fmt: skip
    return replace(rec, candidate=None, ob_zone_id=zid), ZoneState(
        zone, "confirmed", b.candle.close_time, b.bar
    )


def _fvg_in_move(
    b: _Bar, rec: DispRecord, fvgs: Sequence[Fvg], zones: dict[str, ZoneState]
) -> ZoneState | None:
    for gap in reversed(fvgs):
        if gap.direction != rec.disp.direction or gap.bar - 1 < rec.disp.first_bar:
            continue
        zid = b.key.zone_id("fvg", gap.direction, gap.origin_time, gap.low, gap.high)
        if zid in zones:
            return zones[zid]
    return None


def _opposing_level(levels: Sequence[Level], direction: str, zone: Zone) -> int | None:
    if direction == "bull":
        above = [lv.price for lv in levels if lv.side == "buy" and lv.price > zone.high]
        return min(above) if above else None
    below = [lv.price for lv in levels if lv.side == "sell" and lv.price < zone.low]
    return max(below) if below else None


@dataclass(frozen=True, slots=True)
class _SetupInputs:
    records: Sequence[DispRecord]
    zones: dict[str, ZoneState]
    fvgs: Sequence[Fvg]
    sweeps: Sequence[SweepRec]
    levels: Sequence[Level]
    htf: HigherTfContext | None


def _setup(b: _Bar, brk: Event, inp: _SetupInputs) -> SetupCandidate | None:
    profile = PROFILE_BY_TF.get(b.key.timeframe)
    direction = brk.direction
    same = [r for r in inp.records if r.disp.direction == direction]
    if profile is None or direction is None or not same:
        return None
    rec = max(same, key=lambda r: (r.disp.end_bar, -r.disp.candles))
    ob = inp.zones.get(rec.ob_zone_id) if rec.ob_zone_id else None
    fvg = _fvg_in_move(b, rec, inp.fvgs, inp.zones)
    primary = ob or fvg
    if primary is None:
        return None
    window = int(b.const("sweep_window_bars"))
    sweeps = [s for s in inp.sweeps if s.direction == direction and b.bar - s.bar <= window]
    sweep = sweeps[-1].event_id if sweeps else None
    patterns = (brk.type, "displacement", *(("sweep",) if sweep else ()),
                *(("fvg",) if fvg else ()), *(("ob",) if ob else ()))  # fmt: skip
    pz = primary.zone
    k = b.key
    c = b.candle
    return SetupCandidate(
        id=setup_id(k.instrument, k.timeframe, profile, direction, brk.id, k.settings_hash),
        instrument=k.instrument, timeframe=k.timeframe, profile=profile, direction=direction,
        break_event_id=brk.id, break_type=brk.type, patterns=patterns,
        sessions=sessions_of(c.open_time, b.const("sessions_ny")), spread=c.ask_c - c.bid_c,
        atr_k=b.atr_k, displacement_event_id=rec.event_id, displacement_strong=rec.disp.strong,
        sweep_event_id=sweep, ob_zone_id=ob.zone.id if ob else None,
        fvg_zone_id=fvg.zone.id if fvg else None,
        ob_pre_touched=bool(ob and ob.zone.pre_confirmation_touch),
        invalidation=pz.low if direction == "bull" else pz.high,
        opposing_level=_opposing_level(inp.levels, direction, pz),
        origin_time=pz.origin_time, confirm_time=c.close_time, settings_hash=k.settings_hash,
        rule_version=k.rule_version, context=inp.htf,
    )  # fmt: skip


def _lifecycle(b: _Bar, old: Sequence[ZoneState], out: _Out) -> list[ZoneState]:
    """Steps (9) and (10) for zones that existed before this candle."""
    kept = []
    for zs in old:
        zs, moves = advance_zone(zs, b.candle)
        out.transitions += [(zs.zone.id, m, b.candle.close_time) for m in moves]
        zs, expired = expire_zone(zs, b.bar, b.cfg.zone_max_age, b.cfg.zone_max_retests,
                                  b.candle.close_time)  # fmt: skip
        if expired:
            out.transitions.append((zs.zone.id, "expired", b.candle.close_time))
        if zs.state in ACTIVE_STATES:
            kept.append(zs)
    return kept


def step(
    state: SeriesState,
    candle: Candle,
    cfg: Settings,
    *,
    instrument: str,
    timeframe: str,
    rule_version: str,
    htf: HigherTfContext | None = None,
) -> tuple[SeriesState, StepOutput]:
    """Process one closed candle.

    Args:
        state: State after the previous candle.
        candle: The candle that just closed (complete; open time after the previous one).
        cfg: Validated settings.
        instrument: Instrument code (part of every ID).
        timeframe: Series timeframe.
        rule_version: Active rule version (part of every row).
        htf: Higher-timeframe context as of this close, attached to setup candidates.

    Returns:
        The new state and this candle's output.

    Raises:
        OutOfOrderCandle: If ``candle`` does not open after the previous candle.
    """
    if state.last_open_time is not None and candle.open_time <= state.last_open_time:
        raise OutOfOrderCandle(f"{candle.open_time} is not after {state.last_open_time}")
    key = SeriesKey(instrument, timeframe, rule_version, cfg.hash(rule_version))
    bar = state.bar_index + 1
    atr = atr_update(state.atr, candle, int(cfg.constants["atr_period"]))
    b = _Bar(key, cfg, candle, bar, atr.atr_k, (*state.window, candle)[-WINDOW:])
    out = _Out()
    # (3) rollover
    boxes, periods = roll_boxes(state.boxes, candle, timeframe, cfg.constants["sessions_ny"])
    # (4)-(5) swings, trend, BOS and CHoCH
    pivot, ext = cfg.internal_pivot_for(timeframe), cfg.external_pivot
    internal_swings = confirm_swings(b.window, bar, pivot, pivot)
    internal, internal_breaks = _structure_step(b, "internal", state.internal, internal_swings, out)
    external, _ = _structure_step(
        b, "external", state.external, confirm_swings(b.window, bar, ext, ext), out
    )
    # (6) FVG
    fvgs, new_zones = _fvg_step(b, state.recent_fvgs, out)
    # (7) sweeps and breakouts, then new levels
    levels, level_events, ended = check_levels(state.levels, candle, bar, key)
    out.events += level_events
    out.levels += ended
    sweep_keep = bar - int(cfg.constants["sweep_window_bars"])
    sweeps = [s for s in state.recent_sweeps if s.bar >= sweep_keep]
    sweeps += [SweepRec(e.direction, bar, e.id) for e in level_events  # type: ignore[arg-type]
               if e.type == "sweep"]  # fmt: skip
    levels, changes = register_levels(
        levels, internal_swings, periods, candle=candle, bar=bar, atr_k=atr.atr_k,
        eq_tol_m=cfg.eq_tol_m, key=key,
    )  # fmt: skip
    out.levels += changes
    # (8) displacement, OB promotion, setup candidates
    records = _displacement_step(b, state.displacements, internal, out)
    used = [u for u in state.ob_used if u > bar - WINDOW]
    for brk in internal_breaks:
        for i, rec in enumerate(records):
            cand = rec.candidate
            if rec.disp.direction != brk.direction or cand is None:
                continue
            if cand.bar in used:
                # Another displacement already promoted this candle: point at its zone.
                zid = key.zone_id("ob", rec.disp.direction, cand.origin_time, cand.low, cand.high)
                records[i] = replace(rec, candidate=None, ob_zone_id=zid)
                continue
            records[i], zs = _promote(b, rec, cand, brk, out)
            new_zones.append(zs)
            used.append(cand.bar)
    zone_map = {zs.zone.id: zs for zs in (*state.zones, *new_zones)}
    inputs = _SetupInputs(records, zone_map, fvgs, sweeps, levels, htf)
    for brk in internal_breaks:
        setup = _setup(b, brk, inputs)
        if setup is not None:
            out.setups.append(setup)
    # (9)-(10) lifecycle and expiry of zones that existed before this candle; level expiry
    zones = [*_lifecycle(b, state.zones, out), *new_zones]
    levels, expired = expire_levels(levels, bar, int(cfg.constants["level_max_age"]),
                                    candle.close_time)  # fmt: skip
    out.levels += expired
    new_state = replace(
        state,
        bar_index=bar,
        window=b.window,
        last_open_time=candle.open_time,
        last_close_time=candle.close_time,
        atr=atr,
        internal=internal,
        external=external,
        recent_fvgs=fvgs,
        boxes=boxes,
        levels=levels,
        zones=tuple(zones),
        displacements=tuple(records),
        ob_used=tuple(used),
        recent_sweeps=tuple(sweeps),
    )
    return new_state, out.freeze()
