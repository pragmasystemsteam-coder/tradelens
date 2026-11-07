"""``step``: apply one closed candle to a series (DD 3.1, 3.4; FR-SMC-01..06, FR-SMC-11).

Order inside a step (DD 3.4, the parts built so far): (1) order check, (2) ATR, (4) confirm
swings, (5) trend start and structure breaks, (6) FVG. Internal structure uses pivot
``internal_pivot_for(timeframe)`` (3, or 5 on 4h and 1d); external uses ``external_pivot``.
Every output carries ``confirm_time`` = this candle's close, so nothing is known before the
candle that revealed it (no look-ahead). IDs are deterministic (DD 3.8).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from tradelens_engine.arith import atr_update
from tradelens_engine.events import Event, StructureName, Zone
from tradelens_engine.ids import event_id, zone_id
from tradelens_engine.rules.fvg import detect_fvg
from tradelens_engine.rules.structure import Structure, add_swing, detect_breaks
from tradelens_engine.rules.swings import Swing, confirm_swings
from tradelens_engine.series import RECENT_FVGS, WINDOW, SeriesState
from tradelens_engine.settings import Settings
from tradelens_engine.types import Candle

FVG_BARS = 3


class OutOfOrderCandle(ValueError):  # noqa: N818 - name fixed by the design (DD 3.4)
    """A candle whose open time is not after the previous one; the engine never skips."""


@dataclass(frozen=True, slots=True)
class StepOutput:
    """What one candle produced (level changes and setups join in tasks 1.5 and 1.6)."""

    events: tuple[Event, ...] = ()
    new_zones: tuple[Zone, ...] = ()
    zone_transitions: tuple[tuple[str, str, datetime], ...] = ()


@dataclass(frozen=True, slots=True)
class _Ctx:
    instrument: str
    timeframe: str
    rule_version: str
    settings_hash: str

    def event(
        self, type_: str, structure: StructureName, direction: str | None, level: int,
        origin: datetime, confirm: datetime,
    ) -> Event:  # fmt: skip
        eid = event_id(
            self.instrument, self.timeframe, type_, structure, direction, origin, confirm,
            level, self.settings_hash,
        )  # fmt: skip
        return Event(
            eid, self.instrument, self.timeframe, type_, structure, direction, level,  # type: ignore[arg-type]
            origin, confirm, self.settings_hash, self.rule_version,
        )  # fmt: skip


def _structure_step(
    ctx: _Ctx, name: StructureName, st: Structure, swings: list[Swing], candle: Candle,
    atr_k: int | None, buf_m: int,
) -> tuple[Structure, list[Event]]:  # fmt: skip
    events: list[Event] = []
    for swing in swings:
        st = add_swing(st, swing)
        kind = "swing_high" if swing.kind == "high" else "swing_low"
        events.append(
            ctx.event(kind, name, None, swing.price, swing.origin_time, swing.confirm_time)
        )
    st, breaks = detect_breaks(st, candle, atr_k, buf_m)
    events.extend(
        ctx.event(b.type, name, b.direction, b.level.price, b.origin_time, b.confirm_time)
        for b in breaks
    )
    return st, events


def step(
    state: SeriesState,
    candle: Candle,
    cfg: Settings,
    *,
    instrument: str,
    timeframe: str,
    rule_version: str,
) -> tuple[SeriesState, StepOutput]:
    """Process one closed candle.

    Args:
        state: State after the previous candle.
        candle: The candle that just closed (complete; open time after the previous one).
        cfg: Validated settings.
        instrument: Instrument code (part of every ID).
        timeframe: Series timeframe.
        rule_version: Active rule version (part of every row).

    Returns:
        The new state and this candle's output.

    Raises:
        OutOfOrderCandle: If ``candle`` does not open after the previous candle.
    """
    if state.last_open_time is not None and candle.open_time <= state.last_open_time:
        raise OutOfOrderCandle(f"{candle.open_time} is not after {state.last_open_time}")
    ctx = _Ctx(instrument, timeframe, rule_version, cfg.hash(rule_version))
    bar = state.bar_index + 1
    atr = atr_update(state.atr, candle, int(cfg.constants["atr_period"]))
    window = (*state.window, candle)[-WINDOW:]
    buf_m = int(cfg.constants["bos_buffer_m"])
    events: list[Event] = []
    structures: dict[StructureName, Structure] = {}
    plan: tuple[tuple[StructureName, Structure, int], ...] = (
        ("internal", state.internal, cfg.internal_pivot_for(timeframe)),
        ("external", state.external, cfg.external_pivot),
    )
    for name, st, pivot in plan:
        swings = confirm_swings(window, bar, pivot, pivot)
        new_st, new_events = _structure_step(ctx, name, st, swings, candle, atr.atr_k, buf_m)
        structures[name] = new_st
        events.extend(new_events)
    zones: list[Zone] = []
    transitions: list[tuple[str, str, datetime]] = []
    recent = state.recent_fvgs
    if len(window) >= FVG_BARS:
        gap = detect_fvg(window[-3], window[-2], window[-1], bar, atr.atr_k, cfg.fvg_min_m)
        if gap is not None:
            zid = zone_id(
                "fvg", instrument, timeframe, gap.direction, gap.origin_time, gap.low, gap.high,
                ctx.settings_hash,
            )  # fmt: skip
            zones.append(
                Zone(zid, "fvg", instrument, timeframe, gap.direction, gap.low, gap.high,
                     gap.origin_time, gap.confirm_time, ctx.settings_hash, rule_version)
            )  # fmt: skip
            # FR-ZONE-01: an FVG is detected and confirmed at the same close.
            transitions += [
                (zid, "detected", gap.confirm_time),
                (zid, "confirmed", gap.confirm_time),
            ]
            recent = (*recent, gap)[-RECENT_FVGS:]
    new_state = replace(
        state,
        bar_index=bar,
        window=window,
        last_open_time=candle.open_time,
        last_close_time=candle.close_time,
        atr=atr,
        internal=structures["internal"],
        external=structures["external"],
        recent_fvgs=recent,
    )
    return new_state, StepOutput(tuple(events), tuple(zones), tuple(transitions))
