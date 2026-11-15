"""SQL for watchlists and their items (DD 2.6). Every query filters by the owner (NFR-10)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

LIST = text(
    "SELECT w.id, w.name, COALESCE(array_agg(i.instrument ORDER BY i.added_at, i.instrument)"
    " FILTER (WHERE i.instrument IS NOT NULL), '{}') AS instruments FROM watchlists w"
    " LEFT JOIN watchlist_items i ON i.watchlist_id = w.id WHERE w.user_id = :u"
    " GROUP BY w.id ORDER BY w.created_at, w.id"
)
ONE = text("SELECT id, name FROM watchlists WHERE id = :id AND user_id = :u")
ITEMS = text(
    "SELECT instrument FROM watchlist_items WHERE watchlist_id = :id ORDER BY added_at, instrument"
)
COUNT = text("SELECT count(*) FROM watchlists WHERE user_id = :u")
INSERT = text(
    "INSERT INTO watchlists (user_id, name) VALUES (:u, :name) RETURNING id, name, created_at"
)
RENAME = text("UPDATE watchlists SET name = :name WHERE id = :id AND user_id = :u RETURNING id")
DELETE = text("DELETE FROM watchlists WHERE id = :id AND user_id = :u RETURNING id")
ADD_ITEM = text(
    "INSERT INTO watchlist_items (watchlist_id, instrument) VALUES (:id, :i) ON CONFLICT DO NOTHING"
)
REMOVE_ITEM = text("DELETE FROM watchlist_items WHERE watchlist_id = :id AND instrument = :i")
LOCK_USER = text("SELECT id FROM users WHERE id = :u FOR UPDATE")


class DuplicateNameError(Exception):
    """A watchlist with this name already exists for the user."""


def list_watchlists(conn: Connection, user_id: str) -> list[dict[str, Any]]:
    """The user's watchlists with their instruments, oldest first."""
    rows = conn.execute(LIST, {"u": user_id}).mappings()
    return [{"id": str(r["id"]), "name": r["name"], "instruments": list(r["instruments"])}
            for r in rows]  # fmt: skip


def find(conn: Connection, user_id: str, watchlist_id: str) -> dict[str, Any] | None:
    """One of the user's watchlists, or None (also for someone else's)."""
    row = conn.execute(ONE, {"id": watchlist_id, "u": user_id}).mappings().first()
    return None if row is None else {"id": str(row["id"]), "name": row["name"]}


def items(conn: Connection, watchlist_id: str) -> list[str]:
    """Instrument codes of a watchlist in the order they were added."""
    return [r[0] for r in conn.execute(ITEMS, {"id": watchlist_id})]


def lock_owner(conn: Connection, user_id: str) -> None:
    """Serialise one user's watchlist changes (the count check and the insert)."""
    conn.execute(LOCK_USER, {"u": user_id})


def count(conn: Connection, user_id: str) -> int:
    """How many watchlists the user has."""
    return int(conn.execute(COUNT, {"u": user_id}).scalar() or 0)


def insert(conn: Connection, user_id: str, name: str) -> dict[str, Any]:
    """Create a watchlist.

    Raises:
        DuplicateNameError: The user already has one with this name.
    """
    try:
        with conn.begin_nested():
            row = conn.execute(INSERT, {"u": user_id, "name": name}).mappings().one()
    except IntegrityError as exc:
        raise DuplicateNameError(name) from exc
    return {"id": str(row["id"]), "name": row["name"]}


def rename(conn: Connection, user_id: str, watchlist_id: str, name: str) -> bool:
    """Rename; False when not found.

    Raises:
        DuplicateNameError: The user already has one with this name.
    """
    try:
        with conn.begin_nested():
            hit = conn.execute(RENAME, {"id": watchlist_id, "u": user_id, "name": name}).first()
    except IntegrityError as exc:
        raise DuplicateNameError(name) from exc
    return hit is not None


def delete(conn: Connection, user_id: str, watchlist_id: str) -> bool:
    """Delete with its items; False when not found."""
    return conn.execute(DELETE, {"id": watchlist_id, "u": user_id}).first() is not None


def add_item(conn: Connection, watchlist_id: str, instrument: str) -> None:
    """Add an instrument (no-op when present)."""
    conn.execute(ADD_ITEM, {"id": watchlist_id, "i": instrument})


def remove_item(conn: Connection, watchlist_id: str, instrument: str) -> None:
    """Remove an instrument (no-op when absent)."""
    conn.execute(REMOVE_ITEM, {"id": watchlist_id, "i": instrument})
