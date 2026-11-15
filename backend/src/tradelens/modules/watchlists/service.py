"""Watchlists: create, rename, delete, items and the detail view (DD 4.2, 4.3; FR-WATCH-01/02).

Counts are checked against ``max_watchlists`` and ``max_watchlist_items`` with the owner row
locked, so two parallel requests cannot pass the same check. After a downgrade nothing is
deleted: extra watchlists stay readable but cannot grow (DD 4.2).
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from redis.exceptions import RedisError
from sqlalchemy import Connection

from tradelens.core.errors import ApiError, not_found
from tradelens.core.keys import price_key
from tradelens.core.limits import Limits
from tradelens.modules.market_data.public import instrument_rows, series_status_rows
from tradelens.modules.scanner.public import best_setups
from tradelens.modules.watchlists import repository

STATUS_TIMEFRAME = "5m"  # the worker writes one status per instrument on the 5m series


def _conflict(name: str) -> ApiError:
    return ApiError(409, "conflict", f"You already have a watchlist named {name!r}")


def _valid_id(watchlist_id: str) -> str:
    try:
        return str(uuid.UUID(watchlist_id))
    except ValueError as exc:
        raise not_found("Watchlist not found") from exc


def _owned(conn: Connection, user_id: str, watchlist_id: str) -> dict[str, Any]:
    found = repository.find(conn, user_id, _valid_id(watchlist_id))
    if found is None:
        raise not_found("Watchlist not found")
    return found


def list_all(conn: Connection, user_id: str, limits: Limits) -> dict[str, Any]:
    """``GET /watchlists``."""
    return {"items": repository.list_watchlists(conn, user_id),
            "limits": {"max_watchlists": limits["max_watchlists"],
                       "max_watchlist_items": limits["max_watchlist_items"]}}  # fmt: skip


def create(conn: Connection, user_id: str, limits: Limits, name: str) -> dict[str, Any]:
    """``POST /watchlists``.

    Raises:
        ApiError: 403 ``plan_required`` or 422 ``plan_limit`` at the cap; 409 on a duplicate.
    """
    repository.lock_owner(conn, user_id)
    limits.require_room("max_watchlists", repository.count(conn, user_id))
    try:
        row = repository.insert(conn, user_id, name)
    except repository.DuplicateNameError as exc:
        raise _conflict(name) from exc
    return {**row, "instruments": []}


def rename(conn: Connection, user_id: str, watchlist_id: str, name: str) -> dict[str, Any]:
    """``PATCH /watchlists/{id}``."""
    wid = _owned(conn, user_id, watchlist_id)["id"]
    try:
        repository.rename(conn, user_id, wid, name)
    except repository.DuplicateNameError as exc:
        raise _conflict(name) from exc
    return {"id": wid, "name": name, "instruments": repository.items(conn, wid)}


def delete(conn: Connection, user_id: str, watchlist_id: str) -> None:
    """``DELETE /watchlists/{id}``."""
    if not repository.delete(conn, user_id, _valid_id(watchlist_id)):
        raise not_found("Watchlist not found")


def add_item(
    conn: Connection, user_id: str, limits: Limits, watchlist_id: str, instrument: str
) -> None:
    """``PUT /watchlists/{id}/items/{instrument}`` (idempotent)."""
    wid = _owned(conn, user_id, watchlist_id)["id"]
    inst = next((r for r in instrument_rows(conn) if r["code"] == instrument), None)
    if inst is None:
        raise not_found("Instrument not found")
    limits.require_asset(inst["asset_class"])
    repository.lock_owner(conn, user_id)
    current = repository.items(conn, wid)
    if instrument in current:
        return
    limits.require_room("max_watchlist_items", len(current))
    repository.add_item(conn, wid, instrument)


def remove_item(conn: Connection, user_id: str, watchlist_id: str, instrument: str) -> None:
    """``DELETE /watchlists/{id}/items/{instrument}``."""
    wid = _owned(conn, user_id, watchlist_id)["id"]
    repository.remove_item(conn, wid, instrument)


def _price(redis: Any, code: str) -> int | None:  # noqa: ANN401 - redis.Redis
    try:
        raw = redis.get(price_key(code))
    except (RedisError, OSError):
        return None
    return None if raw is None else int(json.loads(raw)["mid"])


def detail(
    conn: Connection,
    redis: Any,  # noqa: ANN401 - redis.Redis
    user_id: str,
    limits: Limits,
    watchlist_id: str,
    profile_version_id: str | None,
) -> dict[str, Any]:
    """``GET /watchlists/{id}``: last price, data status and best setup per instrument.

    Raises:
        ApiError: 404 when not the user's; 403 ``plan_required`` for a profile without
            ``custom_settings`` (profiles arrive in task 3.7).
    """
    wl = _owned(conn, user_id, watchlist_id)
    if profile_version_id is not None:
        limits.require_flag("custom_settings")
        raise not_found("Profile not found")
    codes = repository.items(conn, wl["id"])
    meta = {r["code"]: r for r in instrument_rows(conn)}
    status = {r["instrument"]: r["status"] for r in series_status_rows(conn)
              if r["timeframe"] == STATUS_TIMEFRAME}  # fmt: skip
    best = best_setups(conn, codes)
    rows = []
    for code in codes:
        entitled = limits.allows_asset(meta[code]["asset_class"])
        rows.append({
            "instrument": code, "display_name": meta[code]["display_name"],
            "asset_class": meta[code]["asset_class"], "price_scale": meta[code]["price_scale"],
            "available": entitled,
            "last_price": _price(redis, code) if entitled else None,
            "data_status": status.get(code, "ok"),
            "best_setup": best.get(code) if entitled else None, "custom_applied": False,
        })  # fmt: skip
    return {"id": wl["id"], "name": wl["name"], "items": rows}
