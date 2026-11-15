"""Rows for API tests: setups (with their break event and zone), series status and states.

Setups are inserted directly (not through the worker) so each test controls instrument,
timeframe, direction, patterns, sessions, scores and status exactly.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import text

from tradelens.modules.analysis.public import official_settings

REPO = Path(__file__).resolve().parents[2]
T0 = datetime(2026, 11, 16, 9, 0, tzinfo=UTC)
PROFILE = {"15m": "scalping", "1h": "intraday", "4h": "swing"}
ASSET = {"EUR_USD": "forex", "GBP_USD": "forex", "USD_JPY": "forex", "XAU_USD": "metal",
         "XAG_USD": "metal", "WTICO_USD": "energy", "BCO_USD": "energy"}  # fmt: skip
FACTORS = [
    {"code": "break", "score": "Q", "points": 25, "max": 25, "reason": "strong"},
    {"code": "sweep", "score": "Q", "points": 20, "max": 20, "reason": "sweep_found"},
    {"code": "fvg", "score": "Q", "points": 0, "max": 20, "reason": "no_fvg"},
    {"code": "ob_fresh", "score": "Q", "points": 15, "max": 15, "reason": "ob_fresh"},
    {"code": "room", "score": "Q", "points": 15, "max": 15, "reason": "room_ge2"},
    {"code": "spread_session", "score": "Q", "points": 5, "max": 5, "reason": "ok"},
    {"code": "htf_trend", "score": "C", "points": 40, "max": 40, "reason": "agree_all"},
    {"code": "htf_zone", "score": "C", "points": 0, "max": 30, "reason": "none"},
    {"code": "ltf_confirm", "score": "C", "points": 0, "max": 30, "reason": "pending"},
]


def rule_doc():
    return json.loads((REPO / "config" / "rules" / "r1.0.json").read_text(encoding="utf-8"))


def official_hash():
    return official_settings(rule_doc()).hash("r1.0")


def hexid():
    return uuid.uuid4().hex


def insert_setup(conn, instrument="EUR_USD", timeframe="1h", direction="bull", combined=70,
                 patterns=("bos", "displacement", "ob"), sessions=("london",), status="confirmed",
                 confirm_time=None, q=None, c=None, sid=None, counter_trend=False):  # fmt: skip
    """Insert a setup with its break event, OB zone and revision 1; returns its ID."""
    h, sid = official_hash(), sid or hexid()
    t = confirm_time or T0
    ev, zone = hexid(), hexid()
    q = combined if q is None else q
    c = combined if c is None else c
    conn.execute(text(
        "INSERT INTO market_events (id, instrument, timeframe, settings_hash, rule_version, type,"
        " structure, direction, level, origin_time, confirm_time) VALUES (:id, :i, :tf, :h,"
        " 'r1.0', 'bos', 'internal', :d, 108100, :o, :t)"),
        {"id": ev, "i": instrument, "tf": timeframe, "h": h, "d": direction,
         "o": t - timedelta(hours=1), "t": t})  # fmt: skip
    conn.execute(text(
        "INSERT INTO zones (id, kind, instrument, timeframe, settings_hash, rule_version,"
        " direction, low, high, origin_time, confirm_time, state, state_time) VALUES (:id, 'ob',"
        " :i, :tf, :h, 'r1.0', :d, 108000, 108050, :o, :t, 'confirmed', :t)"),
        {"id": zone, "i": instrument, "tf": timeframe, "h": h, "d": direction,
         "o": t - timedelta(hours=3), "t": t})  # fmt: skip
    conn.execute(text(
        "INSERT INTO setups (id, instrument, asset_class, timeframe, profile, settings_hash,"
        " rule_version, scoring_version, direction, break_event_id, break_type, patterns,"
        " sessions, spread, q, c, combined, counter_trend, factors, explanation, ob_zone_id,"
        " invalidation, opposing_level, status, status_time, origin_time, confirm_time)"
        " VALUES (:id, :i, :a, :tf, :p, :h, 'r1.0', 's1.0', :d, :ev, 'bos', :pat, :ses, 0, :q,"
        " :c, :comb, :ct, CAST(:f AS jsonb), 'Bullish break with displacement.', :z, 108000,"
        " 108300, :st, :t, :o, :t)"),
        {"id": sid, "i": instrument, "a": ASSET[instrument], "tf": timeframe,
         "p": PROFILE[timeframe], "h": h, "d": direction, "ev": ev, "pat": list(patterns),
         "ses": list(sessions), "q": q, "c": c, "comb": combined, "ct": counter_trend,
         "f": json.dumps(FACTORS), "z": zone, "st": status, "o": t - timedelta(hours=3),
         "t": t})  # fmt: skip
    conn.execute(text(
        "INSERT INTO setup_revisions (setup_id, rev, q, c, combined, status, factors, reason,"
        " effective_time) VALUES (:id, 1, :q, :c, :comb, 'confirmed', CAST(:f AS jsonb),"
        " 'created', :t)"),
        {"id": sid, "q": q, "c": c, "comb": combined, "f": json.dumps(FACTORS),
         "t": t})  # fmt: skip
    return sid


def set_status(conn, instrument, status="ok", when=T0):
    conn.execute(text(
        "INSERT INTO series_status (instrument, timeframe, last_candle_time, status,"
        " delayed_since, last_checked_at) VALUES (:i, '5m', :t, :s, :ds, :t)"
        " ON CONFLICT (instrument, timeframe) DO UPDATE SET status = EXCLUDED.status,"
        " delayed_since = EXCLUDED.delayed_since,"
        " last_candle_time = EXCLUDED.last_candle_time"),
        {"i": instrument, "t": when, "s": status,
         "ds": when if status == "delayed" else None})  # fmt: skip
