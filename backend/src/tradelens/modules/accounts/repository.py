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


# ---------------------------------------------------------------- sign-up and tokens (task 3.2)
# A concurrent sign-up with the same e-mail inserts nothing instead of failing.
INSERT_CUSTOMER = text(
    "INSERT INTO users (email, password_hash, name, timezone, trading_style, role)"
    " VALUES (:email, :password_hash, :name, :timezone, :trading_style, 'customer')"
    " ON CONFLICT (email) WHERE deleted_at IS NULL DO NOTHING RETURNING id"
)
SELECT_USER_BY_ID = text(
    f"SELECT {USER_COLUMNS} FROM users u WHERE u.id = :id AND u.deleted_at IS NULL"  # noqa: S608
)
INSERT_TOKEN = text(
    "INSERT INTO email_tokens (token_hash, user_id, purpose, expires_at)"
    " VALUES (:token_hash, :user_id, :purpose, :expires_at)"
)
# One use: the UPDATE succeeds only for an unused, unexpired token of a live user.
USE_TOKEN = text(
    "UPDATE email_tokens t SET used_at = :now FROM users u"
    " WHERE t.token_hash = :token_hash AND t.purpose = :purpose AND t.used_at IS NULL"
    " AND t.expires_at > :now AND u.id = t.user_id AND u.deleted_at IS NULL"
    " RETURNING t.user_id"
)
RETIRE_TOKENS = text(
    "UPDATE email_tokens SET used_at = :now"
    " WHERE user_id = :user_id AND purpose = :purpose AND used_at IS NULL"
)
MARK_VERIFIED = text(
    "UPDATE users SET email_verified_at = :now WHERE id = :id AND email_verified_at IS NULL"
    " RETURNING id"
)
SET_PASSWORD = text("UPDATE users SET password_hash = :password_hash WHERE id = :id")
REVOKE_ALL_SESSIONS = text(
    "UPDATE sessions SET revoked_at = :now WHERE user_id = :user_id AND revoked_at IS NULL"
    " RETURNING id"
)
PROFILE_COLUMNS = ("name", "timezone", "trading_style", "billing_country")


def insert_customer(
    conn: Connection, email: str, password_hash: str, name: str, timezone: str,
    trading_style: str,
) -> str | None:  # fmt: skip
    """Insert an unverified customer; None when a live user already has this e-mail."""
    params = {"email": email, "password_hash": password_hash, "name": name,
              "timezone": timezone, "trading_style": trading_style}  # fmt: skip
    found = conn.execute(INSERT_CUSTOMER, params).scalar()
    return None if found is None else str(found)


def find_user_by_id(conn: Connection, user_id: str) -> dict[str, Any] | None:
    """A live user by ID, with the password hash."""
    row = conn.execute(SELECT_USER_BY_ID, {"id": user_id}).mappings().first()
    return None if row is None else dict(row)


def insert_token(
    conn: Connection, token_hash: str, user_id: str, purpose: str, expires_at: datetime
) -> None:
    """Store the SHA-256 of an e-mailed token."""
    conn.execute(INSERT_TOKEN, {"token_hash": token_hash, "user_id": user_id,
                                "purpose": purpose, "expires_at": expires_at})  # fmt: skip


def use_token(conn: Connection, token_hash: str, purpose: str, now: datetime) -> str | None:
    """Spend a token; the user ID, or None when unknown, used, expired or the user is gone."""
    found = conn.execute(USE_TOKEN, {"token_hash": token_hash, "purpose": purpose,
                                     "now": now}).scalar()  # fmt: skip
    return None if found is None else str(found)


def retire_tokens(conn: Connection, user_id: str, purpose: str, now: datetime) -> None:
    """Make every unused token of this purpose unusable (a newer link replaces them)."""
    conn.execute(RETIRE_TOKENS, {"user_id": user_id, "purpose": purpose, "now": now})


def mark_verified(conn: Connection, user_id: str, now: datetime) -> bool:
    """Set ``email_verified_at``; True only the first time."""
    return conn.execute(MARK_VERIFIED, {"id": user_id, "now": now}).first() is not None


def set_password(conn: Connection, user_id: str, password_hash: str) -> None:
    """Replace the Argon2id hash."""
    conn.execute(SET_PASSWORD, {"id": user_id, "password_hash": password_hash})


def revoke_all_sessions(conn: Connection, user_id: str, now: datetime) -> list[str]:
    """Revoke every live session of a user; returns their IDs."""
    return [r[0] for r in conn.execute(REVOKE_ALL_SESSIONS, {"user_id": user_id, "now": now})]


def update_profile(conn: Connection, user_id: str, fields: dict[str, Any]) -> None:
    """Update the given profile columns (names checked against ``PROFILE_COLUMNS``)."""
    cols = [c for c in PROFILE_COLUMNS if c in fields]
    if not cols:
        return
    sets = ", ".join(f"{c} = :{c}" for c in cols)
    # S608: column names come from the fixed PROFILE_COLUMNS list; values are bound.
    conn.execute(text(f"UPDATE users SET {sets} WHERE id = :id"),  # noqa: S608
                 {**{c: fields[c] for c in cols}, "id": user_id})  # fmt: skip


# Account deletion (DD 4.6, FR-ACC-06): one transaction removes the user's own data and
# scrubs the row; subscriptions, payments, refunds, audit entries and trial claims stay.
# The alert, profile and notification tables have no module of their own yet (task 3.7).
PURGE = tuple(
    text(sql)
    for sql in (
        "DELETE FROM sessions WHERE user_id = :id",
        "DELETE FROM email_tokens WHERE user_id = :id",
        "DELETE FROM watchlists WHERE user_id = :id",
        "DELETE FROM alert_deliveries WHERE user_id = :id",
        "DELETE FROM alert_rules WHERE user_id = :id",
        "DELETE FROM user_profiles WHERE user_id = :id",
        "DELETE FROM notifications WHERE user_id = :id",
        "UPDATE users SET email = 'deleted+' || id::text || '@invalid', name = '',"
        " password_hash = '', totp_secret_enc = NULL, deleted_at = :now WHERE id = :id",
    )
)


def purge_user(conn: Connection, user_id: str, now: datetime) -> None:
    """Delete a user's personal data and scrub the user row."""
    for statement in PURGE:
        conn.execute(statement, {"id": user_id, "now": now})
