"""Series state: everything ``step`` needs between candles (DD 3.2), JSON round-trippable.

The worker saves ``to_json()`` in ``series_state`` after every close and reloads it with
``from_json``; the step-vs-run test proves a reload changes nothing. It holds the window, ATR,
both structures, recent FVGs, the running day/week/session boxes, active liquidity levels,
active zones with their lifecycle counters, recent displacements with their order-block
candidates, the OB candles already used and recent sweeps.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from tradelens_engine.arith import AtrState
from tradelens_engine.codec import decode, encode
from tradelens_engine.rules.fvg import Fvg
from tradelens_engine.rules.lifecycle import ZoneState
from tradelens_engine.rules.liquidity import Boxes, Level
from tradelens_engine.rules.order_blocks import DispRecord
from tradelens_engine.rules.structure import Structure
from tradelens_engine.rules.swings import Swing
from tradelens_engine.timefmt import iso, parse_iso
from tradelens_engine.types import Candle, Dir

WINDOW = 64  # the largest pivot (20/20) needs 41 candles
RECENT_FVGS = 6
STATE_VERSION = 2  # 1 = Day 2 (no levels, zones or displacements); bump on any layout change


class StateVersionError(ValueError):
    """Saved state written by another state layout; the worker rebuilds it from candles."""


@dataclass(frozen=True, slots=True)
class SweepRec:
    """A sweep in the last ``sweep_window_bars`` + 1 bars (FR-MTF-03 "sweep" pattern)."""

    direction: Dir
    bar: int
    event_id: str


@dataclass(frozen=True, slots=True)
class SeriesState:
    """Immutable per-series state; ``bar_index`` counts candles processed (first = 1)."""

    bar_index: int = 0
    window: tuple[Candle, ...] = ()
    last_open_time: datetime | None = None
    last_close_time: datetime | None = None
    atr: AtrState = field(default_factory=AtrState)
    internal: Structure = field(default_factory=Structure)
    external: Structure = field(default_factory=Structure)
    recent_fvgs: tuple[Fvg, ...] = ()
    boxes: Boxes = field(default_factory=Boxes)
    levels: tuple[Level, ...] = ()
    zones: tuple[ZoneState, ...] = ()
    displacements: tuple[DispRecord, ...] = ()
    ob_used: tuple[int, ...] = ()
    recent_sweeps: tuple[SweepRec, ...] = ()

    def to_json(self) -> dict[str, Any]:
        """JSON-serialisable form (integers, booleans and ISO-8601 UTC strings only)."""
        return {
            "v": STATE_VERSION,
            "bar_index": self.bar_index,
            "window": [_candle_out(c) for c in self.window],
            "last_open_time": _opt_iso(self.last_open_time),
            "last_close_time": _opt_iso(self.last_close_time),
            "atr": [self.atr.prev_close, self.atr.tr_count, self.atr.tr_sum, self.atr.atr_k],
            "internal": _structure_out(self.internal),
            "external": _structure_out(self.external),
            "recent_fvgs": [_fvg_out(f) for f in self.recent_fvgs],
            "boxes": encode(self.boxes),
            "levels": encode(self.levels),
            "zones": encode(self.zones),
            "displacements": encode(self.displacements),
            "ob_used": list(self.ob_used),
            "recent_sweeps": encode(self.recent_sweeps),
        }

    @classmethod
    def from_json(cls, obj: dict[str, Any]) -> SeriesState:
        """Inverse of :meth:`to_json`.

        Raises:
            StateVersionError: If ``obj`` was written by another state layout.
            ValueError: If ``obj`` is corrupt (missing fields or wrong types).
        """
        if obj.get("v") != STATE_VERSION:
            raise StateVersionError(f"series state version {obj.get('v')!r} != {STATE_VERSION}")
        prev_close, tr_count, tr_sum, atr_k = obj["atr"]
        return cls(
            bar_index=obj["bar_index"],
            window=tuple(_candle_in(c) for c in obj["window"]),
            last_open_time=_opt_parse(obj["last_open_time"]),
            last_close_time=_opt_parse(obj["last_close_time"]),
            atr=AtrState(prev_close, tr_count, tr_sum, atr_k),
            internal=_structure_in(obj["internal"]),
            external=_structure_in(obj["external"]),
            recent_fvgs=tuple(_fvg_in(f) for f in obj["recent_fvgs"]),
            boxes=decode(Boxes, obj["boxes"]),
            levels=decode(tuple[Level, ...], obj["levels"]),
            zones=decode(tuple[ZoneState, ...], obj["zones"]),
            displacements=decode(tuple[DispRecord, ...], obj["displacements"]),
            ob_used=decode(tuple[int, ...], obj["ob_used"]),
            recent_sweeps=decode(tuple[SweepRec, ...], obj["recent_sweeps"]),
        )


def _opt_iso(dt: datetime | None) -> str | None:
    return None if dt is None else iso(dt)


def _opt_parse(text: str | None) -> datetime | None:
    return None if text is None else parse_iso(text)


def _candle_out(c: Candle) -> list[Any]:
    return [iso(c.open_time), iso(c.close_time), c.o, c.h, c.l, c.c, c.bid_c, c.ask_c]


def _candle_in(v: list[Any]) -> Candle:
    return Candle(parse_iso(v[0]), parse_iso(v[1]), v[2], v[3], v[4], v[5], v[6], v[7])


def _swing_out(s: Swing | None) -> list[Any] | None:
    if s is None:
        return None
    return [s.kind, s.price, s.bar, iso(s.origin_time), iso(s.confirm_time)]


def _swing_in(v: list[Any] | None) -> Swing | None:
    if v is None:
        return None
    return Swing(v[0], v[1], v[2], parse_iso(v[3]), parse_iso(v[4]))


def _swings_in(values: list[list[Any]]) -> tuple[Swing, ...]:
    if any(v is None for v in values):
        raise ValueError("corrupt series state: null swing in a swing list")
    return tuple(Swing(v[0], v[1], v[2], parse_iso(v[3]), parse_iso(v[4])) for v in values)


def _structure_out(st: Structure) -> dict[str, Any]:
    return {
        "trend": st.trend,
        "highs": [_swing_out(s) for s in st.highs],
        "lows": [_swing_out(s) for s in st.lows],
        "unbroken_highs": [_swing_out(s) for s in st.unbroken_highs],
        "unbroken_lows": [_swing_out(s) for s in st.unbroken_lows],
        "protected_high": _swing_out(st.protected_high),
        "protected_low": _swing_out(st.protected_low),
        "protect_after": st.protect_after,
    }


def _structure_in(obj: dict[str, Any]) -> Structure:
    return Structure(
        trend=obj["trend"],
        highs=_swings_in(obj["highs"]),
        lows=_swings_in(obj["lows"]),
        unbroken_highs=_swings_in(obj["unbroken_highs"]),
        unbroken_lows=_swings_in(obj["unbroken_lows"]),
        protected_high=_swing_in(obj["protected_high"]),
        protected_low=_swing_in(obj["protected_low"]),
        protect_after=obj["protect_after"],
    )


def _fvg_out(f: Fvg) -> list[Any]:
    return [f.direction, f.low, f.high, iso(f.origin_time), iso(f.confirm_time), f.bar]


def _fvg_in(v: list[Any]) -> Fvg:
    return Fvg(v[0], v[1], v[2], parse_iso(v[3]), parse_iso(v[4]), v[5])
