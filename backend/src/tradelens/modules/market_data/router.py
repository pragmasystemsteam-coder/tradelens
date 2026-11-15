"""``/instruments``, ``/prices`` and ``/status/data`` (DD 4.2; FR-DATA-05, FR-DATA-06; task 2.5).

Prices come from the worker's Redis snapshots (``price:{instrument}``); a snapshot older than
``PRICE_STALE_AFTER_SECONDS`` is reported ``stale``. Commodities are listed but marked
unavailable, and their prices and status are left out, on a plan without them (DD 4.3).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from redis.exceptions import RedisError
from sqlalchemy import Connection

from tradelens.core.config import AppConfig
from tradelens.core.deps import Viewer, get_clock, get_config, get_conn, get_redis, get_viewer
from tradelens.core.keys import price_key
from tradelens.modules.market_data.repository import instrument_rows, series_status_rows

router = APIRouter(prefix="/api/v1", tags=["market"])
MAX_PRICE_INSTRUMENTS = 20


def _iso(t: datetime | None) -> str | None:
    return None if t is None else t.strftime("%Y-%m-%dT%H:%M:%SZ")


@router.get("/instruments")
def list_instruments(
    viewer: Annotated[Viewer, Depends(get_viewer)],
    conn: Annotated[Connection, Depends(get_conn, scope="function")],
) -> dict[str, Any]:
    """All instruments; ``available`` is false outside the user's asset classes."""
    return {"items": [{**r, "available": viewer.limits.allows_asset(r["asset_class"])}
                      for r in instrument_rows(conn)]}  # fmt: skip


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@router.get("/prices")
def list_prices(
    *,
    instruments: Annotated[str, Query(max_length=400)] = "",
    viewer: Annotated[Viewer, Depends(get_viewer)],
    conn: Annotated[Connection, Depends(get_conn, scope="function")],
    redis: Annotated[Any, Depends(get_redis)],  # noqa: ANN401 - redis.Redis
    cfg: Annotated[AppConfig, Depends(get_config)],
    clock: Annotated[Callable[[], datetime], Depends(get_clock)],
) -> dict[str, Any]:
    """Latest price snapshot per entitled instrument (none until the worker has one)."""
    wanted = [c.strip() for c in instruments.split(",") if c.strip()][:MAX_PRICE_INSTRUMENTS]
    known = {r["code"]: r for r in instrument_rows(conn)}
    codes = [c for c in (wanted or list(known)) if c in known
             and viewer.limits.allows_asset(known[c]["asset_class"])]  # fmt: skip
    now = clock()
    items = []
    for code in codes:
        try:
            raw = redis.get(price_key(code))
        except (RedisError, OSError):
            raw = None
        if raw is None:
            continue
        snap = json.loads(raw)
        age = (now - _parse_time(snap["time"])).total_seconds()
        stale = bool(snap.get("stale")) or age > cfg.price_stale_after_seconds
        items.append({"instrument": code, "bid": snap["bid"], "ask": snap["ask"],
                      "mid": snap["mid"], "price_scale": snap["price_scale"],
                      "time": snap["time"], "stale": stale})  # fmt: skip
    return {"items": items}


@router.get("/status/data")
def data_status(
    viewer: Annotated[Viewer, Depends(get_viewer)],
    conn: Annotated[Connection, Depends(get_conn, scope="function")],
) -> dict[str, Any]:
    """Per series ``{instrument, timeframe, status, last_candle_time, delayed_since}``."""
    items = [{"instrument": r["instrument"], "timeframe": r["timeframe"], "status": r["status"],
              "last_candle_time": _iso(r["last_candle_time"]),
              "delayed_since": _iso(r["delayed_since"])}
             for r in series_status_rows(conn)
             if viewer.limits.allows_asset(r["asset_class"])]  # fmt: skip
    return {"items": items}
