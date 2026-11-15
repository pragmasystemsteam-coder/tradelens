"""Scanner cache rows: confirmed setups ranked per tab and timeframe (DD 4.2 /setups; task 2.3).

The worker rebuilds the cache after every close pass from the stored setups, so the API can
answer ``/setups`` from Redis (key ``scanner:{direction}:{timeframe}``) and fall back to the
database. Rows follow the ``/setups`` row shape; sorting is combined desc, confirm time desc,
then id (DD 4.2).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, text

DIRECTIONS = ("bull", "bear")
SETUP_TIMEFRAMES = ("15m", "1h", "4h")

SCANNER_ROWS = text(
    "SELECT s.id, s.instrument, i.display_name, s.asset_class, i.price_scale, s.timeframe,"
    " s.profile, s.direction, s.patterns, s.sessions, s.q, s.c, s.combined, s.counter_trend,"
    " z.low AS zone_low, z.high AS zone_high, z.state AS zone_state, s.invalidation, s.spread,"
    " s.status, s.confirm_time FROM setups s JOIN instruments i ON i.code = s.instrument"
    " JOIN zones z ON z.id = s.primary_zone_id"
    " WHERE s.settings_hash = :h AND s.status = 'confirmed'"
)


def _iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def scanner_row(r: Mapping[str, Any], high_quality: int) -> dict[str, Any]:
    """One ``/setups`` row from a joined database row (DD 4.2)."""
    return {
        "id": r["id"], "instrument": r["instrument"], "display_name": r["display_name"],
        "asset_class": r["asset_class"], "price_scale": r["price_scale"],
        "timeframe": r["timeframe"], "profile": r["profile"], "direction": r["direction"],
        "patterns": list(r["patterns"]), "sessions": list(r["sessions"]), "q": r["q"],
        "c": r["c"], "combined": r["combined"], "high_quality": r["combined"] >= high_quality,
        "counter_trend": r["counter_trend"],
        "zone": {"low": r["zone_low"], "high": r["zone_high"]}, "zone_state": r["zone_state"],
        "invalidation": r["invalidation"], "spread": r["spread"], "status": r["status"],
        "confirm_time": _iso(r["confirm_time"]),
    }  # fmt: skip


def rank(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Rows sorted combined desc, confirm time desc, then id asc (DD 4.2).

    Three stable sorts, least significant key first; ISO times sort like the times they name.
    """
    out = sorted((dict(r) for r in rows), key=lambda r: r["id"])
    out.sort(key=lambda r: r["confirm_time"], reverse=True)
    out.sort(key=lambda r: r["combined"], reverse=True)
    return out


def group_rows(rows: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """Rows grouped by ``(direction, timeframe)``, each list ranked; every key present."""
    groups: dict[tuple[str, str], list[Mapping[str, Any]]] = {
        (d, tf): [] for d in DIRECTIONS for tf in SETUP_TIMEFRAMES
    }
    for row in rows:
        groups.setdefault((row["direction"], row["timeframe"]), []).append(row)
    return {key: rank(items) for key, items in groups.items()}


def load_scanner_rows(
    conn: Connection, settings_hash: str, high_quality: int
) -> list[dict[str, Any]]:
    """Every confirmed setup of the official settings as ``/setups`` rows (unsorted)."""
    result = conn.execute(SCANNER_ROWS, {"h": settings_hash}).mappings()
    return [scanner_row(dict(r), high_quality) for r in result]
