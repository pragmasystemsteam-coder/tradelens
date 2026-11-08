"""Liquidity levels, period and session boxes, sweeps, breakouts and EQH/EQL (DD 3.4).

Implements FR-SMC-07 (levels), FR-SMC-08 (sweeps and breakouts) and FR-DATA-04 (days, weeks
and sessions on New York time):

* Every level has one side: buy-side above price (swing high, EQH, PDH, PWH, session highs)
  or sell-side below (the lows). At most one active level per (side, price): a second kind at
  the same price joins the existing level's ``kinds``.
* PD, PW and session levels exist only after their period completes, i.e. on the first candle
  of the next period; only the latest completed instance of each kind is active and the older
  one ends ``superseded``. Session levels exist on 5m, 15m and 1h only.
* A level older than ``level_max_age`` bars ends ``expired``.
* For each active level born before this candle: a close beyond it is a breakout; a wick beyond
  it with the close back inside on the same candle is a sweep (CD-18). A close exactly on the
  level is neither.
* EQH/EQL: a new internal swing high within ``eq_tol_m`` thousandths of ATR of an active
  swing-high or EQH level merges with it into one EQH level at the highest price; the member
  ends ``merged``. Mirror for lows. Without an ATR nothing merges.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Literal

from tradelens_engine.arith import le_atr
from tradelens_engine.events import Event, SeriesKey
from tradelens_engine.rules.swings import Swing
from tradelens_engine.timefmt import iso
from tradelens_engine.timekeys import ny_day_key, ny_week_key, sessions_of
from tradelens_engine.types import Candle, Side

EndReason = Literal["swept", "breakout", "superseded", "merged", "expired"]
ChangeKind = Literal["created", "updated", "ended"]
SESSION_TIMEFRAMES = frozenset({"5m", "15m", "1h"})
SESSION_PREFIX = {"asian": "asian", "london": "london", "new_york": "ny"}
SWING_KINDS: dict[str, tuple[str, str]] = {
    "buy": ("swing_high", "eqh"),
    "sell": ("swing_low", "eql"),
}


@dataclass(frozen=True, slots=True)
class Level:
    """A ``liquidity_levels`` row; ``born_bar`` (state only) is the bar that registered it."""

    id: str
    instrument: str
    timeframe: str
    kinds: tuple[str, ...]
    side: Side
    price: int
    structure: str | None
    origin_time: datetime
    confirm_time: datetime
    born_bar: int
    settings_hash: str
    rule_version: str
    end_time: datetime | None = None
    end_reason: EndReason | None = None
    ended_by: str | None = None

    def to_json(self) -> dict[str, Any]:
        """The DB row as plain JSON (times as ISO-8601 UTC)."""
        return {
            "id": self.id, "instrument": self.instrument, "timeframe": self.timeframe,
            "kinds": list(self.kinds), "side": self.side, "price": self.price,
            "structure": self.structure, "origin_time": iso(self.origin_time),
            "confirm_time": iso(self.confirm_time), "settings_hash": self.settings_hash,
            "rule_version": self.rule_version,
            "end_time": None if self.end_time is None else iso(self.end_time),
            "end_reason": self.end_reason, "ended_by": self.ended_by,
        }  # fmt: skip


@dataclass(frozen=True, slots=True)
class LevelChange:
    """A level created, updated (kinds changed) or ended by the candle that closed at ``at``.

    ``level`` is the row after the change.
    """

    change: ChangeKind
    level: Level
    at: datetime

    def to_json(self) -> dict[str, Any]:
        """Plain JSON form."""
        return {"change": self.change, "level": self.level.to_json(), "at": iso(self.at)}


@dataclass(frozen=True, slots=True)
class Box:
    """Running high and low of one day, week or session; times are the extreme candles' opens."""

    name: str
    key: str
    high: int
    high_time: datetime
    low: int
    low_time: datetime


@dataclass(frozen=True, slots=True)
class Period:
    """A completed day, week or session: the level kinds and prices it produces."""

    high_kind: str
    low_kind: str
    high: int
    high_time: datetime
    low: int
    low_time: datetime


@dataclass(frozen=True, slots=True)
class Boxes:
    """The running boxes of a series."""

    day: Box | None = None
    week: Box | None = None
    sessions: tuple[Box, ...] = ()


def _extend(box: Box | None, name: str, key: str, c: Candle) -> Box:
    if box is None:
        return Box(name, key, c.h, c.open_time, c.l, c.open_time)
    # Strict comparisons: on a plateau the first candle stays the origin.
    high, high_time = (c.h, c.open_time) if c.h > box.high else (box.high, box.high_time)
    low, low_time = (c.l, c.open_time) if c.l < box.low else (box.low, box.low_time)
    return Box(name, key, high, high_time, low, low_time)


def _period(box: Box, high_kind: str, low_kind: str) -> Period:
    return Period(high_kind, low_kind, box.high, box.high_time, box.low, box.low_time)


def roll_boxes(
    boxes: Boxes, candle: Candle, timeframe: str, sessions_ny: Mapping[str, Sequence[str]]
) -> tuple[Boxes, tuple[Period, ...]]:
    """Step (3) of DD 3.4: complete the boxes this candle is outside of, then extend them.

    Args:
        boxes: Running boxes before the candle.
        candle: The candle that just closed.
        timeframe: Series timeframe (sessions only on 5m, 15m and 1h).
        sessions_ny: Session name to [start, end] New York times.

    Returns:
        The new boxes and the periods completed by this candle (day, week, then sessions).
    """
    day_key = ny_day_key(candle.open_time).isoformat()
    week_key = ny_week_key(candle.open_time)
    periods: list[Period] = []
    day, week = boxes.day, boxes.week
    if day is not None and day.key != day_key:
        periods.append(_period(day, "pdh", "pdl"))
        day = None
    if week is not None and week.key != week_key:
        periods.append(_period(week, "pwh", "pwl"))
        week = None
    names = sessions_of(candle.open_time, sessions_ny) if timeframe in SESSION_TIMEFRAMES else ()
    running: dict[str, Box] = {}
    for box in boxes.sessions:
        if box.name in names and box.key == day_key:
            running[box.name] = box
        else:
            prefix = SESSION_PREFIX[box.name]
            periods.append(_period(box, f"{prefix}_high", f"{prefix}_low"))
    sessions = tuple(_extend(running.get(name), name, day_key, candle) for name in names)
    new = Boxes(
        _extend(day, "day", day_key, candle), _extend(week, "week", week_key, candle), sessions
    )
    return new, tuple(periods)


def _new_level(
    key: SeriesKey, kind: str, side: Side, price: int, structure: str | None,
    origin: datetime, confirm: datetime, bar: int,
) -> Level:  # fmt: skip
    return Level(
        key.level_id(kind, side, origin, price), key.instrument, key.timeframe, (kind,), side,
        price, structure, origin, confirm, bar, key.settings_hash, key.rule_version,
    )  # fmt: skip


def _end(lv: Level, reason: EndReason, at: datetime, by: str | None = None) -> Level:
    return replace(lv, end_time=at, end_reason=reason, ended_by=by)


def _add(active: list[Level], changes: list[LevelChange], new: Level, at: datetime) -> str:
    """Add ``new`` unless an active level has its side and price; returns the holder's ID."""
    for i, lv in enumerate(active):
        if lv.side == new.side and lv.price == new.price:
            extra = tuple(k for k in new.kinds if k not in lv.kinds)
            if extra:
                # The new kind restarts the age, or a fresh PDH on an old swing price would
                # expire with the old swing (review).
                born = max(lv.born_bar, new.born_bar)
                active[i] = replace(lv, kinds=(*lv.kinds, *extra), born_bar=born)
                changes.append(LevelChange("updated", active[i], at))
            return lv.id
    active.append(new)
    changes.append(LevelChange("created", new, at))
    return new.id


def _supersede(active: list[Level], changes: list[LevelChange], kind: str, at: datetime) -> None:
    for i, lv in enumerate(active):
        if kind not in lv.kinds:
            continue
        if lv.kinds == (kind,):
            changes.append(LevelChange("ended", _end(lv, "superseded", at), at))
            del active[i]
        else:
            active[i] = replace(lv, kinds=tuple(k for k in lv.kinds if k != kind))
            changes.append(LevelChange("updated", active[i], at))
        return  # only one active level holds a period kind


def _add_swing(
    active: list[Level], changes: list[LevelChange], swing: Swing, *, key: SeriesKey,
    confirm: datetime, bar: int, atr_k: int | None, eq_tol_m: int,
) -> None:  # fmt: skip
    side: Side = "buy" if swing.kind == "high" else "sell"
    own, equal = SWING_KINDS[side]
    allowed = {own, equal}
    near = [
        lv
        for lv in active
        if lv.side == side
        and set(lv.kinds) <= allowed
        and le_atr(abs(lv.price - swing.price), eq_tol_m, atr_k)
    ]
    if not near:
        _add(active, changes, _new_level(key, own, side, swing.price, "internal",
                                         swing.origin_time, confirm, bar), confirm)  # fmt: skip
        return
    member = min(near, key=lambda lv: (abs(lv.price - swing.price), -lv.born_bar))
    price = max(member.price, swing.price) if side == "buy" else min(member.price, swing.price)
    active.remove(member)
    # Origin = the new swing: one EQH per new swing keeps the ID unique (DD 3.8).
    eq_level = _new_level(key, equal, side, price, "internal", swing.origin_time, confirm, bar)
    holder = _add(active, changes, eq_level, confirm)
    changes.append(LevelChange("ended", _end(member, "merged", confirm, holder), confirm))


def register_levels(
    levels: tuple[Level, ...],
    swings: Sequence[Swing],
    periods: Sequence[Period],
    *,
    candle: Candle,
    bar: int,
    atr_k: int | None,
    eq_tol_m: int,
    key: SeriesKey,
) -> tuple[tuple[Level, ...], list[LevelChange]]:
    """Register this candle's completed periods and new internal swings (after sweeps).

    Args:
        levels: Active levels.
        swings: Internal swings confirmed by this candle.
        periods: Periods completed by this candle.
        candle: This candle (its close is every new level's ``confirm_time``).
        bar: This candle's bar index (``born_bar`` of new levels).
        atr_k: ATR x1000 or None (no EQH/EQL merge without it).
        eq_tol_m: EQH/EQL tolerance in thousandths of ATR.
        key: Series key for IDs.

    Returns:
        Active levels after registration and the changes in order.
    """
    active: list[Level] = list(levels)
    changes: list[LevelChange] = []
    at = candle.close_time
    for p in periods:
        sides: tuple[tuple[str, Side, int, datetime], ...] = (
            (p.high_kind, "buy", p.high, p.high_time),
            (p.low_kind, "sell", p.low, p.low_time),
        )
        for kind, side, price, origin in sides:
            _supersede(active, changes, kind, at)
            _add(active, changes, _new_level(key, kind, side, price, None, origin, at, bar), at)
    for swing in swings:
        _add_swing(active, changes, swing, key=key, confirm=at, bar=bar, atr_k=atr_k,
                   eq_tol_m=eq_tol_m)  # fmt: skip
    return tuple(active), changes


def check_levels(
    levels: tuple[Level, ...], candle: Candle, bar: int, key: SeriesKey
) -> tuple[tuple[Level, ...], list[Event], list[LevelChange]]:
    """Step (7) of DD 3.4: sweeps and breakouts of levels born before this candle.

    Returns:
        Levels still active, the sweep/breakout events and the ended levels.
    """
    kept: list[Level] = []
    events: list[Event] = []
    changes: list[LevelChange] = []
    c = candle
    for lv in levels:
        found: tuple[Literal["sweep", "breakout"], str, EndReason] | None = None
        if lv.born_bar < bar:
            p = lv.price
            if lv.side == "buy":
                if c.c > p:
                    found = ("breakout", "bull", "breakout")
                elif c.h > p and c.c < p:
                    found = ("sweep", "bear", "swept")
            elif c.c < p:
                found = ("breakout", "bear", "breakout")
            elif c.l < p and c.c > p:
                found = ("sweep", "bull", "swept")
        if found is None:
            kept.append(lv)
            continue
        type_, direction, reason = found
        event = key.event(type_, None, direction, lv.price, lv.origin_time, c.close_time,
                          refs=(("level_id", lv.id),))  # fmt: skip
        events.append(event)
        changes.append(LevelChange("ended", _end(lv, reason, c.close_time, event.id), c.close_time))
    return tuple(kept), events, changes


def expire_levels(
    levels: tuple[Level, ...], bar: int, max_age: int, at: datetime
) -> tuple[tuple[Level, ...], list[LevelChange]]:
    """End levels older than ``max_age`` bars (step 10 of DD 3.4)."""
    kept: list[Level] = []
    changes: list[LevelChange] = []
    for lv in levels:
        if bar - lv.born_bar > max_age:
            changes.append(LevelChange("ended", _end(lv, "expired", at), at))
        else:
            kept.append(lv)
    return tuple(kept), changes
