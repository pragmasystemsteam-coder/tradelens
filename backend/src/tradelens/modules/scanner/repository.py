"""Read-only SQL for the scanner (tables owned by analysis and market_data; DD 2.4, 2.5)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Connection, text

from tradelens.modules.analysis.public import load_scanner_rows, scanner_row

SETUP = text(
    "SELECT s.id, s.instrument, i.display_name, s.asset_class, i.price_scale, s.timeframe,"
    " s.profile, s.direction, s.patterns, s.sessions, s.q, s.c, s.combined, s.counter_trend,"
    " z.low AS zone_low, z.high AS zone_high, z.state AS zone_state, s.invalidation, s.spread,"
    " s.status, s.confirm_time, s.factors, s.explanation, s.opposing_level, s.origin_time,"
    " s.rule_version, s.scoring_version FROM setups s"
    " JOIN instruments i ON i.code = s.instrument JOIN zones z ON z.id = s.primary_zone_id"
    " WHERE s.id = :id AND s.settings_hash = :h"
)
REVISIONS = text(
    "SELECT rev, effective_time, q, c, combined, status, reason FROM setup_revisions"
    " WHERE setup_id = :id ORDER BY rev"
)
TRENDS = text(
    "SELECT timeframe, trend_internal, trend_external FROM series_state"
    " WHERE instrument = :i AND settings_hash = :h"
)
DATA_AS_OF = text(
    "SELECT GREATEST((SELECT max(as_of) FROM series_state WHERE settings_hash = :h),"
    " (SELECT max(confirm_time) FROM setups WHERE settings_hash = :h))"
)
DELAYED = text(
    "SELECT DISTINCT s.instrument, i.asset_class FROM series_status s"
    " JOIN instruments i ON i.code = s.instrument WHERE s.status <> 'ok' ORDER BY s.instrument"
)


def iso(t: datetime | None) -> str | None:
    """UTC ``...Z`` or None."""
    return None if t is None else t.strftime("%Y-%m-%dT%H:%M:%SZ")


def stored_rows(conn: Connection, settings_hash: str, high_quality: int) -> list[dict[str, Any]]:
    """Every confirmed official setup as a ``/setups`` row (the cache fallback)."""
    return load_scanner_rows(conn, settings_hash, high_quality)


def data_as_of(conn: Connection, settings_hash: str) -> str | None:
    """Close time of the newest stepped candle of the official settings."""
    return iso(conn.execute(DATA_AS_OF, {"h": settings_hash}).scalar())


def delayed_instruments(conn: Connection, asset_classes: tuple[str, ...]) -> list[str]:
    """Instruments with any series not ``ok`` (FR-DATA-05), of the given asset classes only."""
    return [r[0] for r in conn.execute(DELAYED) if r[1] in asset_classes]


def fetch_setup(
    conn: Connection, setup_id: str, settings_hash: str, high_quality: int
) -> dict[str, Any] | None:
    """A setup with its ``/setups`` row and the detail columns."""
    r = conn.execute(SETUP, {"id": setup_id, "h": settings_hash}).mappings().first()
    if r is None:
        return None
    raw = dict(r)
    return {"row": scanner_row(raw, high_quality), "asset_class": raw["asset_class"],
            "instrument": raw["instrument"], "profile": raw["profile"],
            "factors": list(raw["factors"]), "explanation": raw["explanation"],
            "opposing_level": raw["opposing_level"], "origin_time": iso(raw["origin_time"]),
            "rule_version": raw["rule_version"],
            "scoring_version": raw["scoring_version"]}  # fmt: skip


def fetch_revisions(conn: Connection, setup_id: str) -> list[dict[str, Any]]:
    """Revisions oldest first (DD 4.2 ``revisions[{at, q, c, combined, status}]``)."""
    return [{"rev": r["rev"], "at": iso(r["effective_time"]), "q": r["q"], "c": r["c"],
             "combined": r["combined"], "status": r["status"], "reason": r["reason"]}
            for r in conn.execute(REVISIONS, {"id": setup_id}).mappings()]  # fmt: skip


def fetch_trends(
    conn: Connection, instrument: str, settings_hash: str
) -> dict[str, tuple[str | None, str | None]]:
    """Timeframe to (internal, external) trend from the saved series states."""
    rows = conn.execute(TRENDS, {"i": instrument, "h": settings_hash})
    return {r[0]: (r[1], r[2]) for r in rows}


BEST = text(
    "SELECT DISTINCT ON (s.instrument) s.instrument, s.id, s.timeframe, s.direction, s.combined,"
    " s.confirm_time FROM setups s WHERE s.settings_hash = :h AND s.status = 'confirmed'"
    " AND s.instrument = ANY(:codes)"
    " ORDER BY s.instrument, s.combined DESC, s.confirm_time DESC, s.id"
)


def best_setups(
    conn: Connection, settings_hash: str, codes: list[str]
) -> dict[str, dict[str, Any]]:
    """The best confirmed setup per instrument (highest combined, newest, then id)."""
    if not codes:
        return {}
    rows = conn.execute(BEST, {"h": settings_hash, "codes": codes}).mappings()
    return {r["instrument"]: {"id": r["id"], "timeframe": r["timeframe"],
                              "direction": r["direction"], "combined": r["combined"],
                              "confirm_time": iso(r["confirm_time"])} for r in rows}  # fmt: skip
