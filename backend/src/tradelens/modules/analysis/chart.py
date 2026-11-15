"""Chart overlays: stored rows for the official settings, on-demand compute for others (task 2.6).

Official settings read what the worker stored (events, zones, liquidity levels, setups, series
state). A preset or profile whose settings the worker does not run is computed here over a
fixed window of candles (DD 4.2: ``chart_history_candles + 1,000``, at most 3,000). Either way
the result is the same dictionaries, so the chart service windows both alike.

Provisional swings come from a saved series state: a candidate that passes the left test and
the right test so far. They are never stored, scored, listed or alerted (FR-SCAN-03).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, text

from tradelens.modules.analysis.process import to_engine
from tradelens.modules.analysis.service import load_active_rule
from tradelens.modules.market_data.public import StoredCandle
from tradelens_engine.run import run
from tradelens_engine.series import SeriesState
from tradelens_engine.settings import Settings
from tradelens_engine.types import Candle

TIMEFRAMES = ("1d", "4h", "1h", "15m", "5m")  # trend strip order (FR-CHART-04)
ACTIVE_ZONE_STATES = ("confirmed", "touched", "mitigated_50", "filled")
# Higher timeframes whose zones a chart shows when ``mtf_detail`` is full (DD 3.5 profiles).
HTF: dict[str, tuple[str, ...]] = {"5m": ("15m", "1h"), "15m": ("1h",), "1h": ("1d", "4h"),
                                   "4h": ("1d",), "1d": ()}  # fmt: skip

EVENTS = text(
    "SELECT id, type, structure, direction, level, origin_time, confirm_time FROM market_events"
    " WHERE instrument = :i AND timeframe = :tf AND settings_hash = :h"
    " AND confirm_time >= :start AND confirm_time <= :end ORDER BY confirm_time, id"
)
ZONES = text(
    "SELECT id, kind, direction, low, high, state, state_time, retests, pre_confirmation_touch,"
    " origin_time, confirm_time FROM zones WHERE instrument = :i AND timeframe = :tf"
    " AND settings_hash = :h AND confirm_time <= :end"
    " AND (state IN ('confirmed','touched','mitigated_50','filled') OR state_time >= :start)"
    " ORDER BY confirm_time, id"
)
HTF_ZONES = text(
    "SELECT timeframe, id, kind, direction, low, high FROM zones WHERE instrument = :i"
    " AND timeframe = ANY(:tfs) AND settings_hash = :h AND confirm_time <= :end"
    " AND state IN ('confirmed','touched','mitigated_50','filled')"
    " ORDER BY timeframe, confirm_time, id"
)
LEVELS = text(
    "SELECT id, kinds, side, price, origin_time, confirm_time, end_time, end_reason"
    " FROM liquidity_levels WHERE instrument = :i AND timeframe = :tf AND settings_hash = :h"
    " AND confirm_time <= :end AND (end_time IS NULL OR end_time >= :start)"
    " ORDER BY confirm_time, id"
)
SETUPS = text(
    "SELECT id, direction, combined, status, primary_zone_id FROM setups WHERE instrument = :i"
    " AND timeframe = :tf AND settings_hash = :h AND confirm_time >= :start"
    " AND confirm_time <= :end ORDER BY confirm_time, id"
)
STATES = text(
    "SELECT timeframe, trend_internal, trend_external, as_of, state FROM series_state"
    " WHERE instrument = :i AND settings_hash = :h"
)
PRESET = text(
    "SELECT code, name, settings, settings_hash FROM presets WHERE rule_version = :v"
    " AND code = :code"
)


def iso(t: datetime | None) -> str | None:
    """UTC ``...Z`` or None."""
    return None if t is None else t.strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True, slots=True)
class OfficialRule:
    """The settings the worker runs: what the scanner and default charts read."""

    version: str
    settings: Settings
    settings_hash: str
    high_quality: int


_rules: dict[str, OfficialRule] = {}


def official_rule(conn: Connection) -> OfficialRule:
    """The active rule version, its official settings and hash, and the high-quality mark."""
    rule = load_active_rule(conn)
    hit = _rules.get(rule.version)
    if hit is None:
        hit = OfficialRule(rule.version, rule.settings, rule.settings.hash(rule.version),
                           int(rule.weights["high_quality"]))  # fmt: skip
        _rules[rule.version] = hit
    return hit


@dataclass(frozen=True, slots=True)
class Preset:
    """A stored preset of the active rule version."""

    code: str
    settings: Settings
    settings_hash: str


def find_preset(conn: Connection, rule: OfficialRule, code: str) -> Preset | None:
    """A preset of the active rule version by code, or None.

    Presets store only the user-settable part; the constants are the rule version's.
    """
    row = conn.execute(PRESET, {"v": rule.version, "code": code}).mappings().first()
    if row is None:
        return None
    constants = rule.settings.to_json()["constants"]
    cfg = Settings.from_json({"user": dict(row["settings"]), "constants": constants})
    return Preset(row["code"], cfg, row["settings_hash"])


@dataclass(frozen=True, slots=True)
class Overlays:
    """Chart overlays of one series (JSON-ready dictionaries, times as ISO strings)."""

    events: list[dict[str, Any]] = field(default_factory=list)
    zones: list[dict[str, Any]] = field(default_factory=list)
    liquidity: list[dict[str, Any]] = field(default_factory=list)
    state: SeriesState | None = None


def _event(r: Mapping[str, Any]) -> dict[str, Any]:
    return {"id": r["id"], "type": r["type"], "structure": r["structure"],
            "direction": r["direction"], "level": r["level"],
            "origin_time": iso(r["origin_time"]),
            "confirm_time": iso(r["confirm_time"])}  # fmt: skip


def _zone(r: Mapping[str, Any]) -> dict[str, Any]:
    return {"id": r["id"], "kind": r["kind"], "direction": r["direction"], "low": r["low"],
            "high": r["high"], "state": r["state"], "state_time": iso(r["state_time"]),
            "retests": r["retests"], "pre_confirmation_touch": r["pre_confirmation_touch"],
            "origin_time": iso(r["origin_time"]),
            "confirm_time": iso(r["confirm_time"])}  # fmt: skip


def _level(r: Mapping[str, Any]) -> dict[str, Any]:
    ended = r["end_time"] is not None
    return {"id": r["id"], "kinds": list(r["kinds"]), "side": r["side"], "price": r["price"],
            "origin_time": iso(r["origin_time"]), "confirm_time": iso(r["confirm_time"]),
            "status": "ended" if ended else "active", "end_reason": r["end_reason"],
            "end_time": iso(r["end_time"])}  # fmt: skip


def window_overlays(
    ov: Overlays, start: datetime, end: datetime, include_inactive: bool
) -> Overlays:
    """Keep what touches ``[start, end]``; invalidated and expired zones only on request."""
    s, e = iso(start) or "", iso(end) or ""
    events = [x for x in ov.events if s <= x["confirm_time"] <= e]
    zones = [z for z in ov.zones if z["confirm_time"] <= e
             and (z["state"] in ACTIVE_ZONE_STATES or z["state_time"] >= s)
             and (include_inactive or z["state"] in ACTIVE_ZONE_STATES)]  # fmt: skip
    levels = [lv for lv in ov.liquidity if lv["confirm_time"] <= e
              and (lv["end_time"] is None or lv["end_time"] >= s)]  # fmt: skip
    return Overlays(events, zones, levels, ov.state)


def stored_overlays(
    conn: Connection, instrument: str, timeframe: str, settings_hash: str, start: datetime,
    end: datetime, include_inactive: bool,
) -> Overlays:  # fmt: skip
    """Overlays of the official settings from stored rows (no engine run)."""
    p = {"i": instrument, "tf": timeframe, "h": settings_hash, "start": start, "end": end}
    ov = Overlays(
        [_event(dict(r)) for r in conn.execute(EVENTS, p).mappings()],
        [_zone(dict(r)) for r in conn.execute(ZONES, p).mappings()],
        [_level(dict(r)) for r in conn.execute(LEVELS, p).mappings()],
    )
    return window_overlays(ov, start, end, include_inactive)


def compute_overlays(
    rows: Sequence[StoredCandle], instrument: str, timeframe: str, cfg: Settings,
    rule_version: str,
) -> Overlays:  # fmt: skip
    """Run the engine over ``rows`` with ``cfg`` and return every overlay (not windowed).

    Args:
        rows: Stored candles, oldest first (the fixed compute window).
        instrument: Instrument code.
        timeframe: Series timeframe.
        cfg: Preset or profile settings.
        rule_version: Rule version (part of IDs).

    Returns:
        Events, zones with their final state, liquidity levels and the final series state.
    """
    candles = [to_engine(r) for r in rows]
    result = run(candles, cfg, instrument=instrument, timeframe=timeframe,
                 rule_version=rule_version)  # fmt: skip
    last: dict[str, tuple[str, datetime]] = {}
    for zid, state, t in result.zone_transitions:
        if state != "detected":
            last[zid] = (state, t)
    retests = {zs.zone.id: zs.retests for zs in result.state.zones}
    zones = []
    for z in result.zones:
        state, t = last.get(z.id, ("confirmed", z.confirm_time))
        zones.append(_zone({"id": z.id, "kind": z.kind, "direction": z.direction, "low": z.low,
                            "high": z.high, "state": state, "state_time": t,
                            "retests": retests.get(z.id, 0),
                            "pre_confirmation_touch": z.pre_confirmation_touch,
                            "origin_time": z.origin_time,
                            "confirm_time": z.confirm_time}))  # fmt: skip
    levels: dict[str, dict[str, Any]] = {}
    for ch in result.level_changes:
        lv = ch.level
        levels[lv.id] = _level({"id": lv.id, "kinds": lv.kinds, "side": lv.side,
                                "price": lv.price, "origin_time": lv.origin_time,
                                "confirm_time": lv.confirm_time, "end_time": lv.end_time,
                                "end_reason": lv.end_reason})  # fmt: skip
    for lv in result.state.levels:
        levels[lv.id] = _level({"id": lv.id, "kinds": lv.kinds, "side": lv.side,
                                "price": lv.price, "origin_time": lv.origin_time,
                                "confirm_time": lv.confirm_time, "end_time": None,
                                "end_reason": None})  # fmt: skip
    events = sorted((_event({"id": e.id, "type": e.type, "structure": e.structure,
                             "direction": e.direction, "level": e.level,
                             "origin_time": e.origin_time, "confirm_time": e.confirm_time})
                     for e in result.events),
                    key=lambda x: (x["confirm_time"], x["id"]))  # fmt: skip
    return Overlays(events, zones, list(levels.values()), result.state)


def _pending(window: Sequence[Candle], n: int, structure: str) -> list[dict[str, Any]]:
    """Candidates with fewer than ``n`` right bars that pass both tests so far (DD 3.4)."""
    out: list[dict[str, Any]] = []
    t = len(window) - 1
    for k in range(max(n, t - n + 1), t + 1):
        left, right, bar = window[k - n : k], window[k + 1 : t + 1], window[k]
        if bar.h > max(b.h for b in left) and all(bar.h >= b.h for b in right):
            out.append({"type": "swing_high", "structure": structure, "price": bar.h,
                        "origin_time": iso(bar.open_time)})  # fmt: skip
        if bar.l < min(b.l for b in left) and all(bar.l <= b.l for b in right):
            out.append({"type": "swing_low", "structure": structure, "price": bar.l,
                        "origin_time": iso(bar.open_time)})  # fmt: skip
    return out


def provisional_swings(state: SeriesState, cfg: Settings, timeframe: str) -> list[dict[str, Any]]:
    """Pending internal and external pivots of a saved state (drawn dashed, never stored)."""
    window = state.window
    return [*_pending(window, cfg.internal_pivot_for(timeframe), "internal"),
            *_pending(window, cfg.external_pivot, "external")]  # fmt: skip


def series_states(
    conn: Connection, instrument: str, settings_hash: str
) -> dict[str, dict[str, Any]]:
    """Timeframe to its ``series_state`` row (trend columns, ``as_of``, state JSON)."""
    rows = conn.execute(STATES, {"i": instrument, "h": settings_hash}).mappings()
    return {r["timeframe"]: dict(r) for r in rows}


def trend_strip(states: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """All five timeframes, highest first; a missing state is neutral (FR-CHART-04)."""
    return [{"timeframe": tf,
             "internal": states[tf]["trend_internal"] if tf in states else "neutral",
             "external": states[tf]["trend_external"] if tf in states else "neutral",
             "as_of": iso(states[tf]["as_of"]) if tf in states else None}
            for tf in TIMEFRAMES]  # fmt: skip


def decode_state(raw: Mapping[str, Any] | None) -> SeriesState | None:
    """A saved state, or None when missing or unreadable."""
    if raw is None:
        return None
    try:
        return SeriesState.from_json(dict(raw))
    except (ValueError, KeyError, TypeError):
        return None


def htf_zones(
    conn: Connection, instrument: str, timeframe: str, settings_hash: str, end: datetime
) -> list[dict[str, Any]]:
    """Active higher-timeframe OBs and FVGs of the official settings (Pro, FR-CHART-03)."""
    tfs = list(HTF.get(timeframe, ()))
    if not tfs:
        return []
    rows = conn.execute(HTF_ZONES, {"i": instrument, "tfs": tfs, "h": settings_hash, "end": end})
    return [dict(r) for r in rows.mappings()]


def series_setups(
    conn: Connection, instrument: str, timeframe: str, settings_hash: str, start: datetime,
    end: datetime,
) -> list[dict[str, Any]]:  # fmt: skip
    """Setups of the series confirmed inside the window."""
    p = {"i": instrument, "tf": timeframe, "h": settings_hash, "start": start, "end": end}
    return [{"id": r["id"], "direction": r["direction"], "combined": r["combined"],
             "status": r["status"], "zone_id": r["primary_zone_id"]}
            for r in conn.execute(SETUPS, p).mappings()]  # fmt: skip


def overlays_json(ov: Overlays) -> dict[str, Any]:
    """Cacheable form of computed overlays (the state is kept as its JSON)."""
    return {"events": ov.events, "zones": ov.zones, "liquidity": ov.liquidity,
            "state": None if ov.state is None else ov.state.to_json()}  # fmt: skip


def overlays_from_json(doc: Mapping[str, Any]) -> Overlays:
    """Inverse of :func:`overlays_json`."""
    return Overlays(list(doc["events"]), list(doc["zones"]), list(doc["liquidity"]),
                    decode_state(doc.get("state")))  # fmt: skip
