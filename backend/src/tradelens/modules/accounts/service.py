"""Accounts: users, sign-in and sessions (DD 2.1, 4.1; FR-ACC-02, FR-ACC-05).

``create-user`` makes operator accounts; sign-in, sessions and logout arrive in task 2.4;
sign-up, verification and password reset in Increment 3. Session cookies hold a random
value; only its HMAC is stored (``core.security``).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy import Connection

from tradelens.core.errors import ApiError, not_authenticated, session_ended
from tradelens.core.security import new_session_token, session_id
from tradelens.modules.accounts import repository

ROLES = ("customer", "support", "admin")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AccountError(ValueError):
    """A user that must not be created."""


def validate_account(email: str, role: str) -> None:
    """Check an e-mail's shape and a role without touching the database.

    Raises:
        AccountError: On a malformed e-mail or an unknown role.
    """
    if not EMAIL.match(email):
        raise AccountError(f"not an email address: {email!r}")
    if role not in ROLES:
        raise AccountError(f"role must be one of {ROLES}")


def create_account(conn: Connection, email: str, role: str, password_hash: str) -> str:
    """Insert a verified user (operator-created accounts skip e-mail verification).

    Args:
        conn: Connection inside the caller's transaction.
        email: E-mail address (case-insensitive, unique among live users).
        role: ``customer``, ``support`` or ``admin``.
        password_hash: Argon2id hash (never the password).

    Returns:
        The new user's UUID.

    Raises:
        AccountError: On a malformed e-mail, an unknown role or an e-mail already in use.
    """
    validate_account(email, role)
    if repository.live_email_exists(conn, email):
        raise AccountError(f"a user with email {email} already exists")
    return repository.insert_user(conn, email, role, password_hash)


# ---------------------------------------------------------------- sign-in and sessions (task 2.4)
TOUCH_EVERY = timedelta(minutes=1)  # last_seen_at is written at most once a minute (DD 4.1)
_hasher = PasswordHasher()
_dummy_hash: list[str] = []


@dataclass(frozen=True, slots=True)
class SessionRules:
    """Session settings from the environment (DD 6.1)."""

    secret: str
    idle_days: int = 7
    max_sessions: int = 2


@dataclass(frozen=True, slots=True)
class LoginResult:
    """A signed-in user, the cookie value, its stored ID and the sessions revoked for it."""

    user: dict[str, Any]
    token: str
    session_id: str
    revoked: tuple[str, ...]


def public_user(user: Mapping[str, Any]) -> dict[str, Any]:
    """The ``user`` object of ``/me`` (never the password hash)."""
    return {"id": str(user["id"]), "email": str(user["email"]), "name": user["name"],
            "timezone": user["timezone"], "trading_style": user["trading_style"],
            "billing_country": user["billing_country"]}  # fmt: skip


def _password_ok(stored: str | None, password: str) -> bool:
    if stored is None:  # same work for an unknown e-mail: no timing hint (no enumeration)
        if not _dummy_hash:
            _dummy_hash.append(_hasher.hash("not-a-real-password"))
        stored, password = _dummy_hash[0], password + "x"
    try:
        return _hasher.verify(stored, password)
    except (VerifyMismatchError, InvalidHashError, VerificationError):
        return False


def login(
    conn: Connection, rules: SessionRules, email: str, password: str, now: datetime,
    user_agent: str | None = None,
) -> LoginResult:  # fmt: skip
    """Check the password and open a session; a third live session ends the oldest (FR-ACC-05).

    Raises:
        ApiError: 401 ``invalid_credentials`` (one message for every failure) or 403
            ``email_not_verified``.
    """
    user = repository.find_user_by_email(conn, email)
    if user is not None:
        # Serialise this user's sign-ins so two at once cannot both miss the other's session
        # and leave three live sessions (FR-ACC-05).
        repository.lock_user(conn, str(user["id"]))
    ok = _password_ok(None if user is None else user["password_hash"], password)
    if user is None or not ok:
        raise ApiError(401, "invalid_credentials", "Email or password is incorrect")
    if user["email_verified_at"] is None:
        raise ApiError(403, "email_not_verified", "Verify your email first")
    token = new_session_token()
    sid = session_id(rules.secret, token)
    uid = str(user["id"])
    repository.insert_session(conn, sid, uid, now, now + timedelta(days=rules.idle_days),
                              None if user_agent is None else user_agent[:300])  # fmt: skip
    live = repository.live_session_ids(conn, uid, now)
    revoked = [s for s in live if s != sid][max(rules.max_sessions - 1, 0) :]
    repository.revoke_sessions(conn, revoked, now)
    return LoginResult(user, token, sid, tuple(revoked))


def resolve_session(
    conn: Connection, rules: SessionRules, token: str, now: datetime
) -> tuple[dict[str, Any], str]:
    """The user of a session cookie; slides the 7-day idle expiry.

    Returns:
        The user row (``session_touched`` is True when the idle expiry was just slid, so the
        caller re-issues the cookies) and the stored session ID.

    Raises:
        ApiError: 401 ``session_ended`` when revoked, ``not_authenticated`` when unknown or idle.
    """
    sid = session_id(rules.secret, token)
    row = repository.find_session(conn, sid)
    if row is None:
        raise not_authenticated()
    if row["revoked_at"] is not None:
        raise session_ended()
    if row["expires_at"] <= now:
        raise not_authenticated()
    row["session_touched"] = now - row["last_seen_at"] >= TOUCH_EVERY
    if row["session_touched"]:
        repository.touch_session(conn, sid, now, now + timedelta(days=rules.idle_days))
    return row, sid


def logout(conn: Connection, sid: str, now: datetime) -> None:
    """Revoke one session."""
    repository.revoke_sessions(conn, [sid], now)
