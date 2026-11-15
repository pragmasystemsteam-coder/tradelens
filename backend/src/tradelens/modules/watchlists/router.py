"""Watchlist endpoints (DD 4.2; FR-WATCH-01, FR-WATCH-02; task 2.7)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection

from tradelens.core.deps import Viewer, get_conn, get_redis, get_viewer
from tradelens.modules.watchlists import service

router = APIRouter(prefix="/api/v1/watchlists", tags=["watchlists"])
ViewerDep = Annotated[Viewer, Depends(get_viewer)]
ConnDep = Annotated[Connection, Depends(get_conn, scope="function")]


class NameIn(BaseModel):
    """``{name}`` of a watchlist."""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=60, pattern=r"\S")


@router.get("")
def list_watchlists(viewer: ViewerDep, conn: ConnDep) -> dict[str, Any]:
    """The user's watchlists and limits."""
    return service.list_all(conn, viewer.user_id, viewer.limits)


@router.post("", status_code=201)
def create_watchlist(body: NameIn, viewer: ViewerDep, conn: ConnDep) -> dict[str, Any]:
    """Create a watchlist (``max_watchlists``)."""
    return service.create(conn, viewer.user_id, viewer.limits, body.name.strip())


@router.get("/{watchlist_id}")
def get_watchlist(
    watchlist_id: str,
    viewer: ViewerDep,
    conn: ConnDep,
    redis: Annotated[Any, Depends(get_redis)],  # noqa: ANN401 - redis.Redis
    profile_version_id: Annotated[str | None, Query(max_length=64)] = None,
) -> dict[str, Any]:
    """Instruments with last price, data status and best setup."""
    return service.detail(conn, redis, viewer.user_id, viewer.limits, watchlist_id,
                          profile_version_id)  # fmt: skip


@router.patch("/{watchlist_id}")
def rename_watchlist(
    watchlist_id: str, body: NameIn, viewer: ViewerDep, conn: ConnDep
) -> dict[str, Any]:
    """Rename a watchlist."""
    return service.rename(conn, viewer.user_id, watchlist_id, body.name.strip())


@router.delete("/{watchlist_id}", status_code=204)
def delete_watchlist(watchlist_id: str, viewer: ViewerDep, conn: ConnDep) -> Response:
    """Delete a watchlist and its items."""
    service.delete(conn, viewer.user_id, watchlist_id)
    return Response(status_code=204)


@router.put("/{watchlist_id}/items/{instrument}", status_code=204)
def add_item(watchlist_id: str, instrument: str, viewer: ViewerDep, conn: ConnDep) -> Response:
    """Add an instrument (idempotent; ``max_watchlist_items``, ``asset_classes``)."""
    service.add_item(conn, viewer.user_id, viewer.limits, watchlist_id, instrument)
    return Response(status_code=204)


@router.delete("/{watchlist_id}/items/{instrument}", status_code=204)
def remove_item(watchlist_id: str, instrument: str, viewer: ViewerDep, conn: ConnDep) -> Response:
    """Remove an instrument."""
    service.remove_item(conn, viewer.user_id, watchlist_id, instrument)
    return Response(status_code=204)
