"""Scanner rules: filters, gating, ranking, keyset pages and setup detail (DD 4.2, 4.3; task 2.5).

Rows come from the worker's Redis lists (``scanner:{direction}:{timeframe}``) and fall back to
the database when a list is missing. Filters run here so cached and stored rows behave the
same. The scanner always shows the official settings (FR-CUST-04).
"""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection

from tradelens.core.errors import not_found, validation_error
from tradelens.core.limits import Limits
from tradelens.modules.analysis.public import official_rule, rank
from tradelens.modules.scanner import repository

TF_PROFILE = {"15m": "scalping", "1h": "intraday", "4h": "swing"}
STYLE_TF = {"scalping": "15m", "intraday": "1h", "swing": "4h"}
DIRECTIONS = ("bull", "bear")
# Profile timeframes (DD 3.5): setup, context and confirmation roles for setup detail.
PROFILE_TFS: dict[str, tuple[tuple[str, str], ...]] = {
    "scalping": (("15m", "setup"), ("1h", "context"), ("5m", "confirmation")),
    "intraday": (("1h", "setup"), ("1d", "context"), ("4h", "context"), ("15m", "confirmation"),
                 ("5m", "confirmation")),
    "swing": (("4h", "setup"), ("1d", "context"), ("1h", "confirmation")),
}  # fmt: skip


@dataclass(frozen=True, slots=True)
class ScannerQuery:
    """``GET /setups`` filters (DD 4.2)."""

    timeframe: str
    direction: str | None = None
    instruments: frozenset[str] = frozenset()
    patterns: frozenset[str] = frozenset()
    match: str = "any"  # CR-006: "any" (at least one pattern) or "all" (every pattern)
    sessions: frozenset[str] = frozenset()
    min_score: int | None = None
    asset_class: str | None = None
    limit: int = 50
    cursor: str | None = None

    @property
    def directions(self) -> tuple[str, ...]:
        """The tabs to read."""
        return DIRECTIONS if self.direction is None else (self.direction,)


def matches(row: Mapping[str, Any], q: ScannerQuery, limits: Limits) -> bool:
    """Whether a ``/setups`` row passes the filters and the user's asset classes."""
    if row["status"] != "confirmed" or row["timeframe"] != q.timeframe:
        return False
    if row["direction"] not in q.directions or not limits.allows_asset(row["asset_class"]):
        return False
    if q.instruments and row["instrument"] not in q.instruments:
        return False
    if q.asset_class and row["asset_class"] != q.asset_class:
        return False
    if q.patterns:
        have = set(row["patterns"])
        if (q.match == "all" and not q.patterns <= have) or not q.patterns & have:
            return False
    if q.sessions and not q.sessions & set(row["sessions"]):
        return False
    return q.min_score is None or row["combined"] >= q.min_score


def _key(row: Mapping[str, Any]) -> tuple[int, str, str]:
    return (int(row["combined"]), str(row["confirm_time"]), str(row["id"]))


def encode_cursor(row: Mapping[str, Any]) -> str:
    """Opaque keyset cursor after ``row`` (combined, confirm time, id)."""
    raw = json.dumps(list(_key(row)), separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[int, str, str]:
    """Inverse of :func:`encode_cursor`.

    Raises:
        ApiError: 400 ``validation_error`` on anything else.
    """
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        combined, confirm, sid = json.loads(raw)
        if type(combined) is not int or not isinstance(confirm, str) or not isinstance(sid, str):
            raise ValueError("cursor fields")
    except (ValueError, binascii.Error, TypeError, json.JSONDecodeError) as exc:
        raise validation_error("cursor", "invalid") from exc
    return combined, confirm, sid


def _after(row: Mapping[str, Any], key: tuple[int, str, str]) -> bool:
    """Whether ``row`` sorts after the cursor key (combined desc, time desc, id asc)."""
    combined, confirm, sid = _key(row)
    if combined != key[0]:
        return combined < key[0]
    if confirm != key[1]:
        return confirm < key[1]
    return sid > key[2]


def page(
    rows: Sequence[Mapping[str, Any]], cursor: str | None, limit: int
) -> tuple[list[dict[str, Any]], str | None]:
    """One page of ranked rows and the cursor of the next page (None at the end)."""
    if cursor is not None:
        key = decode_cursor(cursor)
        rows = [r for r in rows if _after(r, key)]
    items = [dict(r) for r in rows[:limit]]
    more = len(rows) > limit
    return items, encode_cursor(items[-1]) if more and items else None


def scanner_page(
    rows: Iterable[Mapping[str, Any]], q: ScannerQuery, limits: Limits
) -> tuple[list[dict[str, Any]], str | None]:
    """Filter, rank and page rows (cached or stored)."""
    return page(rank(r for r in rows if matches(r, q, limits)), q.cursor, q.limit)


def lock_factors(factors: Iterable[Mapping[str, Any]], mtf_full: bool) -> list[dict[str, Any]]:
    """Factors for setup detail; on ``mtf_detail: strip`` C factors hide points and reason."""
    out = []
    for f in factors:
        locked = f["score"] == "C" and not mtf_full
        out.append({"code": f["code"], "score": f["score"], "max": f["max"],
                    "points": None if locked else f["points"],
                    "reason": None if locked else f["reason"], "locked": locked})  # fmt: skip
    return out


def setup_detail(conn: Connection, setup_id: str, limits: Limits) -> dict[str, Any]:
    """``GET /setups/{id}`` (DD 4.2): row, factors, explanation, MTF strip and revisions.

    Raises:
        ApiError: 404 when unknown (or not of the official settings), 403 ``plan_required``
            for a commodity on a plan without it.
    """
    rule = official_rule(conn)
    row = repository.fetch_setup(conn, setup_id, rule.settings_hash, rule.high_quality)
    if row is None:
        raise not_found("Setup not found")
    limits.require_asset(row["asset_class"])
    trends = repository.fetch_trends(conn, row["instrument"], rule.settings_hash)
    mtf = [{"timeframe": tf, "role": role, "trend_internal": trends.get(tf, (None, None))[0],
            "trend_external": trends.get(tf, (None, None))[1]}
           for tf, role in PROFILE_TFS[row["profile"]]]  # fmt: skip
    return {**row["row"], "factors": lock_factors(row["factors"], limits.mtf_full),
            "explanation": row["explanation"], "opposing_level": row["opposing_level"],
            "origin_time": row["origin_time"], "rule_version": row["rule_version"],
            "scoring_version": row["scoring_version"], "mtf": mtf,
            "revisions": repository.fetch_revisions(conn, setup_id)}  # fmt: skip


def best_setups(conn: Connection, codes: list[str]) -> dict[str, dict[str, Any]]:
    """Best confirmed official setup per instrument (watchlists, FR-WATCH-02)."""
    return repository.best_setups(conn, official_rule(conn).settings_hash, codes)
