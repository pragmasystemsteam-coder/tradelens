"""SQL for users and sessions (DD 2.1)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Connection, text

EMAIL_EXISTS = text("SELECT 1 FROM users WHERE email = :email AND deleted_at IS NULL")
INSERT_USER = text(
    "INSERT INTO users (email, password_hash, role, email_verified_at)"
    " VALUES (:email, :password_hash, :role, now()) RETURNING id"
)


def live_email_exists(conn: Connection, email: str) -> bool:
    """Whether a live (not deleted) user has this e-mail (citext: case-insensitive)."""
    return conn.execute(EMAIL_EXISTS, {"email": email}).first() is not None


def insert_user(conn: Connection, email: str, role: str, password_hash: str) -> str:
    """Insert a user and return its UUID."""
    params = {"email": email, "role": role, "password_hash": password_hash}
    return str(conn.execute(INSERT_USER, params).scalar())


USER_COLUMNS = (
    "u.id, u.email, u.password_hash, u.name, u.timezone, u.trading_style, u.role,"
    " u.billing_country, u.email_verified_at"
)
SELECT_USER_BY_EMAIL = text(
    f"SELECT {USER_COLUMNS} FROM users u WHERE u.email = :email AND u.deleted_at IS NULL"  # noqa: S608
)
INSERT_SESSION = text(
    "INSERT INTO sessions (id, user_id, kind, created_at, last_seen_at, expires_at, user_agent)"
    " VALUES (:id, :user_id, 'app', :now, :now, :expires_at, :user_agent)"
)
SELECT_LIVE_SESSIONS = text(
    "SELECT id FROM sessions WHERE user_id = :user_id AND kind = 'app' AND revoked_at IS NULL"
    " AND expires_at > :now ORDER BY created_at DESC, id DESC"
)
REVOKE_SESSIONS = text(
    "UPDATE sessions SET revoked_at = :now WHERE id = ANY(:ids) AND revoked_at IS NULL"
)
# S608: USER_COLUMNS is a constant; every value is a bound parameter.
SELECT_SESSION = text(
    f"SELECT s.id AS session_id, s.last_seen_at, s.expires_at, s.revoked_at, {USER_COLUMNS}"  # noqa: S608
    " FROM sessions s JOIN users u ON u.id = s.user_id"
    " WHERE s.id = :id AND s.kind = 'app' AND u.deleted_at IS NULL"
)
TOUCH_SESSION = text(
    "UPDATE sessions SET last_seen_at = :now, expires_at = :expires_at WHERE id = :id"
)


def find_user_by_email(conn: Connection, email: str) -> dict[str, Any] | None:
    """A live user by e-mail (case-insensitive), with the password hash."""
    row = conn.execute(SELECT_USER_BY_EMAIL, {"email": email}).mappings().first()
    return None if row is None else dict(row)


def insert_session(
    conn: Connection, sid: str, user_id: str, now: datetime, expires_at: datetime,
    user_agent: str | None,
) -> None:  # fmt: skip
    """Store a new app session under its HMAC ID."""
    conn.execute(INSERT_SESSION, {"id": sid, "user_id": user_id, "now": now,
                                  "expires_at": expires_at, "user_agent": user_agent})  # fmt: skip


def live_session_ids(conn: Connection, user_id: str, now: datetime) -> list[str]:
    """Live app sessions of a user, newest first."""
    rows = conn.execute(SELECT_LIVE_SESSIONS, {"user_id": user_id, "now": now})
    return [r[0] for r in rows]


def revoke_sessions(conn: Connection, ids: list[str], now: datetime) -> None:
    """Revoke sessions (kept, so a revoked cookie answers ``session_ended``)."""
    if ids:
        conn.execute(REVOKE_SESSIONS, {"ids": ids, "now": now})


def find_session(conn: Connection, sid: str) -> dict[str, Any] | None:
    """A session with its user."""
    row = conn.execute(SELECT_SESSION, {"id": sid}).mappings().first()
    return None if row is None else dict(row)


def touch_session(conn: Connection, sid: str, now: datetime, expires_at: datetime) -> None:
    """Slide the idle expiry."""
    conn.execute(TOUCH_SESSION, {"id": sid, "now": now, "expires_at": expires_at})


LOCK_USER = text("SELECT id FROM users WHERE id = :id FOR UPDATE")


def lock_user(conn: Connection, user_id: str) -> None:
    """Lock a user row until the end of the transaction."""
    conn.execute(LOCK_USER, {"id": user_id})
