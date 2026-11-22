"""``GET /setups`` and ``GET /setups/{id}`` (DD 4.2; FR-SCAN-01..06; task 2.5)."""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from redis.exceptions import RedisError
from sqlalchemy import Connection

from tradelens.core.deps import Viewer, get_conn, get_redis, get_viewer
from tradelens.core.errors import not_found
from tradelens.core.keys import scanner_key
from tradelens.modules.scanner import repository
from tradelens.modules.scanner.service import (
    STYLE_TF,
    ScannerQuery,
    official_rule,
    scanner_page,
    setup_detail,
)

router = APIRouter(prefix="/api/v1", tags=["scanner"])
Timeframe = Literal["15m", "1h", "4h"]
Pattern = Literal["sweep", "bos", "choch", "fvg", "ob", "displacement"]
Session = Literal["asian", "london", "new_york"]
SETUP_ID_LEN = 32


def _cached(redis: Any, q: ScannerQuery) -> tuple[list[dict[str, Any]], str | None] | None:  # noqa: ANN401
    """Rows of every needed tab from Redis, or None when any list is missing."""
    rows: list[dict[str, Any]] = []
    as_of: list[str] = []
    try:
        for direction in q.directions:
            raw = redis.get(scanner_key(direction, q.timeframe))
            if raw is None:
                return None
            doc = json.loads(raw)
            rows += doc["items"]
            if doc.get("data_as_of"):
                as_of.append(doc["data_as_of"])
    except (RedisError, OSError, ValueError, KeyError):
        return None
    return rows, max(as_of, default=None)


@router.get("/setups")
def list_setups(
    *,
    instrument: Annotated[list[str] | None, Query()] = None,
    timeframe: Timeframe | None = None,
    direction: Literal["bull", "bear"] | None = None,
    pattern: Annotated[list[Pattern] | None, Query()] = None,
    match: Literal["any", "all"] = "any",
    session: Annotated[list[Session] | None, Query()] = None,
    min_score: Annotated[int | None, Query(ge=0, le=100)] = None,
    asset_class: Literal["forex", "metal", "energy"] | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
    viewer: Annotated[Viewer, Depends(get_viewer)],
    conn: Annotated[Connection, Depends(get_conn, scope="function")],
    redis: Annotated[Any, Depends(get_redis)],  # noqa: ANN401 - redis.Redis
) -> dict[str, Any]:
    """Ranked confirmed setups of the official settings, Redis first (DD 4.2).

    The timeframe selects the profile (decision D-1); without one, the user's trading style
    picks it. Rows outside the user's asset classes are dropped (DD 4.3).
    """
    q = ScannerQuery(timeframe=timeframe or STYLE_TF.get(viewer.trading_style, "1h"),
                     direction=direction, instruments=frozenset(instrument or ()),
                     patterns=frozenset(pattern or ()), match=match,
                     sessions=frozenset(session or ()),
                     min_score=min_score, asset_class=asset_class, limit=limit,
                     cursor=cursor)  # fmt: skip
    cached = _cached(redis, q)
    if cached is None:
        rule = official_rule(conn)
        rows = repository.stored_rows(conn, rule.settings_hash, rule.high_quality)
        as_of = repository.data_as_of(conn, rule.settings_hash)
    else:
        rows, as_of = cached
    items, next_cursor = scanner_page(rows, q, viewer.limits)
    delayed = [i for i in repository.delayed_instruments(conn, viewer.limits.asset_classes)
               if not q.instruments or i in q.instruments]  # fmt: skip
    return {"items": items, "next_cursor": next_cursor, "data_as_of": as_of,
            "series_delayed": delayed}  # fmt: skip


@router.get("/setups/{setup_id}")
def get_setup(
    setup_id: str,
    viewer: Annotated[Viewer, Depends(get_viewer)],
    conn: Annotated[Connection, Depends(get_conn, scope="function")],
) -> dict[str, Any]:
    """Setup detail with factors (C locked on ``mtf_detail: strip``) and revisions."""
    if len(setup_id) != SETUP_ID_LEN or not all(ch in "0123456789abcdef" for ch in setup_id):
        raise not_found("Setup not found")
    return setup_detail(conn, setup_id, viewer.limits)
