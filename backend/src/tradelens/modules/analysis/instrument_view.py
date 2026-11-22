"""Instrument analysis for the scanner and charts (CR-006): read-only, computed on request.

Trend on every timeframe, recent structure events, open zones, active liquidity, every setup of
the series (low scores included), pattern counts, and per direction the current candidate from
``tradelens_engine.scoring.candidates``. Candidates are display only: never stored, ranked or
alerted.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Connection, text

from tradelens.modules.analysis.chart import (
    ACTIVE_ZONE_STATES,
    decode_state,
    iso,
    official_rule,
    series_states,
    trend_strip,
)
from tradelens.modules.analysis.service import load_active_rule
from tradelens_engine.context import PROFILE_BY_TF, build_context
from tradelens_engine.scoring import ScoringConfig
from tradelens_engine.scoring.candidates import (
    LOOKBACK_BARS,
    CandidateView,
    EventIn,
    LevelIn,
    ZoneIn,
    current_candidates,
)
from tradelens_engine.timekeys import sessions_of

RECENT_BARS = 100  # CR-006: events in the last 100 candles count as recent
TF_SECONDS = {"5m": 300, "15m": 900, "1h": 3600, "4h": 14_400, "1d": 86_400}
PATTERNS = ("bos", "choch", "sweep", "fvg", "ob", "displacement")
STRUCTURE_LIMIT = 12

EVENTS = text(
    "SELECT id, type, structure, direction, level, origin_time, confirm_time, details"
    " FROM market_events WHERE instrument = :i AND timeframe = :tf AND settings_hash = :h"
    " AND confirm_time >= :start ORDER BY confirm_time, id"
)
ZONES = text(
    "SELECT id, kind, direction, low, high, state, origin_time, confirm_time,"
    " pre_confirmation_touch FROM zones WHERE instrument = :i AND timeframe = :tf"
    " AND settings_hash = :h AND state IN ('confirmed','touched','mitigated_50','filled')"
    " ORDER BY confirm_time, id"
)
LEVELS = text(
    "SELECT id, kinds, side, price, confirm_time FROM liquidity_levels WHERE instrument = :i"
    " AND timeframe = :tf AND settings_hash = :h AND end_time IS NULL ORDER BY price"
)
SETUPS = text(
    "SELECT id, direction, combined, q, c, status, counter_trend, patterns, break_event_id,"
    " confirm_time FROM setups WHERE instrument = :i AND timeframe = :tf AND settings_hash = :h"
    " AND confirm_time >= :start ORDER BY confirm_time DESC, id"
)


def _details(raw: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON column
    if raw is None:
        return {}
    doc = json.loads(raw) if isinstance(raw, str) else raw
    if isinstance(doc, list):  # stored as (key, value) pairs
        return dict(doc)
    return dict(doc)


def _event_json(r: Mapping[str, Any]) -> dict[str, Any]:
    return {"id": r["id"], "type": r["type"], "structure": r["structure"],
            "direction": r["direction"], "level": r["level"],
            "origin_time": iso(r["origin_time"]),
            "confirm_time": iso(r["confirm_time"])}  # fmt: skip


def _candidate_json(c: CandidateView, mtf_full: bool) -> dict[str, Any]:
    z = c.zone
    zone = None if z is None else {"id": z.id, "kind": z.kind, "low": z.low, "high": z.high,
                                   "state": z.state, "nearby": c.zone_nearby}  # fmt: skip
    return {
        "kind": "candidate", "label": "Candidate, not a setup", "direction": c.direction,
        "break": {"id": c.break_event.id, "type": c.break_event.type,
                  "level": c.break_event.level,
                  "confirm_time": iso(c.break_event.confirm_time)},
        "displacement_id": c.displacement.id if c.displacement else None,
        "sweep_id": c.sweep.id if c.sweep else None,
        "zone": zone,
        "checks": [{"code": k.code, "met": k.met} for k in c.checks],
        "patterns": list(c.patterns),
        "factors": [{"code": f.code, "score": f.score, "max": f.max,
                     "points": None if f.score == "C" and not mtf_full else f.points,
                     "locked": f.score == "C" and not mtf_full} for f in c.factors],
        "q": c.q, "c": c.c if mtf_full else None, "combined": c.combined,
        "counter_trend": c.counter_trend,
    }  # fmt: skip


def instrument_analysis(
    conn: Connection, instrument: Mapping[str, Any], timeframe: str, now: datetime,
    *, mtf_full: bool,
) -> dict[str, Any]:  # fmt: skip
    """``GET /analysis/{instrument}/{tf}`` body (the caller has checked the asset class).

    Args:
        conn: Database connection.
        instrument: The ``instruments`` row (``code``, ``price_scale``, ``normal_spread``).
        timeframe: 5m, 15m, 1h, 4h or 1d.
        now: Current UTC time.
        mtf_full: Pro detail; Free sees C-factor points locked, as on setup detail.

    Returns:
        The analysis document.
    """
    rule = official_rule(conn)
    active = load_active_rule(conn)
    code, h = instrument["code"], rule.settings_hash
    step = TF_SECONDS[timeframe]
    start = now - timedelta(seconds=step * RECENT_BARS)
    p = {"i": code, "tf": timeframe, "h": h, "start": start}
    ev_rows = [dict(r) for r in conn.execute(EVENTS, p).mappings()]
    zone_rows = [dict(r) for r in conn.execute(ZONES, p).mappings()]
    level_rows = [dict(r) for r in conn.execute(LEVELS, p).mappings()]
    setup_rows = [dict(r) for r in conn.execute(SETUPS, p).mappings()]
    states = series_states(conn, code, h)

    counts = dict.fromkeys(PATTERNS, 0)
    for r in ev_rows:
        if r["type"] in counts:
            counts[r["type"]] += 1
    for z in zone_rows:
        if z["kind"] in counts and z["state"] in ACTIVE_ZONE_STATES:
            counts[z["kind"]] += 1

    candidates: list[dict[str, Any]] = []
    profile = PROFILE_BY_TF.get(timeframe)
    if profile is not None:
        decoded = {tf: decode_state(s["state"]) for tf, s in states.items()}
        own = decoded.get(timeframe)
        events = []
        for r in ev_rows:
            det = _details(r["details"])
            events.append(EventIn(r["id"], r["type"], r["structure"], r["direction"],
                                  r["level"], r["origin_time"], r["confirm_time"],
                                  bool(det.get("strong", False)),
                                  int(det.get("candles", 0) or 0)))  # fmt: skip
        zones = [ZoneIn(z["id"], z["kind"], z["direction"], z["low"], z["high"], z["state"],
                        z["origin_time"], z["confirm_time"], bool(z["pre_confirmation_touch"]))
                 for z in zone_rows]  # fmt: skip
        levels = [LevelIn(lv["price"], lv["side"]) for lv in level_rows]
        sessions_ny = active.settings.constants.get("sessions_ny")
        last_open = now - timedelta(seconds=step)
        sessions = sessions_of(last_open, sessions_ny) if sessions_ny else sessions_of(last_open)
        views = current_candidates(
            instrument=code, timeframe=timeframe, profile=profile, settings_hash=h,
            rule_version=rule.version, now=now, tf_seconds=step, events=events, zones=zones,
            levels=levels, atr_k=own.atr.atr_k if own else None,
            context=build_context({k: v for k, v in decoded.items() if v is not None}, profile),
            setup_break_ids=frozenset(s["break_event_id"] for s in setup_rows),
            sessions=sessions, spread=0, constants=active.settings.constants,
            weights=ScoringConfig.from_json(dict(active.weights)),
            normal_spread=int(instrument.get("normal_spread") or 0),
        )  # fmt: skip
        candidates = [_candidate_json(v, mtf_full) for v in views]

    structure = [r for r in ev_rows if r["type"] in ("bos", "choch", "sweep", "displacement")]
    return {
        "instrument": code, "timeframe": timeframe, "price_scale": instrument["price_scale"],
        "as_of": iso(now), "recent_bars": RECENT_BARS, "candidate_bars": LOOKBACK_BARS,
        "trend_strip": trend_strip(states),
        "structure": [_event_json(r) for r in structure[-STRUCTURE_LIMIT:]][::-1],
        "zones": [{"id": z["id"], "kind": z["kind"], "direction": z["direction"],
                   "low": z["low"], "high": z["high"], "state": z["state"],
                   "confirm_time": iso(z["confirm_time"])}
                  for z in zone_rows if z["state"] in ACTIVE_ZONE_STATES][::-1],
        "liquidity": [{"id": lv["id"], "kinds": list(lv["kinds"]), "side": lv["side"],
                       "price": lv["price"]} for lv in level_rows],
        "setups": [{"id": s["id"], "direction": s["direction"], "combined": s["combined"],
                    "q": s["q"], "c": s["c"] if mtf_full else None, "status": s["status"],
                    "counter_trend": s["counter_trend"], "patterns": list(s["patterns"]),
                    "break_event_id": s["break_event_id"],
                    "confirm_time": iso(s["confirm_time"])} for s in setup_rows],
        "pattern_counts": counts,
        "candidates": candidates,
    }  # fmt: skip
