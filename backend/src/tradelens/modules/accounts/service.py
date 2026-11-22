"""Accounts: users, sign-in, sessions, sign-up and recovery (DD 2.1, 4.1, 4.2, 4.6; FR-ACC-01..06).

``create-user`` makes operator accounts; sign-in, sessions and logout arrived in task 2.4;
sign-up, verification, password reset, profile and deletion in task 3.2. E-mailed tokens are
256-bit random values; only their SHA-256 is stored, and each works once. Session cookies hold
a random value; only its HMAC is stored (``core.security``).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy import Connection

from tradelens.core.deps import AccountBilling
from tradelens.core.errors import ApiError, not_authenticated, session_ended
from tradelens.core.security import new_session_token, session_id
from tradelens.modules.accounts import repository
from tradelens.modules.notifications.public import queue_email

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


# ---------------------------------------------------------------- sign-up and recovery (task 3.2)
VERIFY, RESET = "verify", "reset"
ACTIVE_PLAN_MESSAGE = "Your paid plan is active. Confirm cancelling it to delete your account."
StartTrial = Callable[[Connection, str, str, datetime], bool]


@dataclass(frozen=True, slots=True)
class LinkRules:
    """Where e-mailed links point and how long they work (DD 6.1)."""

    app_url: str
    verify_ttl: timedelta = timedelta(hours=24)
    reset_ttl: timedelta = timedelta(hours=1)


def token_hash(token: str) -> str:
    """SHA-256 hex of an e-mailed token (only the hash is stored)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _issue(conn: Connection, user_id: str, purpose: str, ttl: timedelta, now: datetime) -> str:
    """A fresh one-time token; older unused tokens of the purpose stop working."""
    repository.retire_tokens(conn, user_id, purpose, now)
    token = new_session_token()
    repository.insert_token(conn, token_hash(token), user_id, purpose, now + ttl)
    return token


def verification_link(conn: Connection, links: LinkRules, user_id: str, now: datetime) -> str:
    """Issue a verification token and return its link (24 h)."""
    token = _issue(conn, user_id, VERIFY, links.verify_ttl, now)
    return f"{links.app_url}/verify-email?token={token}"


def _send_verification(
    conn: Connection, links: LinkRules, user_id: str, email: str, now: datetime
) -> None:
    link = verification_link(conn, links, user_id, now)
    hours = int(links.verify_ttl.total_seconds() // 3600)
    queue_email(conn, "verify", email, {"link": link, "ttl_hours": hours}, user_id=user_id)


def register(
    conn: Connection, links: LinkRules, email: str, password: str, now: datetime, *,
    name: str = "", timezone: str = "UTC", trading_style: str = "intraday",
) -> None:  # fmt: skip
    """Create an unverified customer and e-mail the verification link (FR-ACC-01).

    An e-mail that already has an account gets an "already registered" mail instead, and the
    caller answers the same 202 either way (no account enumeration). The password is hashed
    first in both cases, so the answer takes the same time.
    """
    password_hash = _hasher.hash(password)
    uid = repository.insert_customer(conn, email, password_hash, name, timezone, trading_style)
    if uid is None:
        existing = repository.find_user_by_email(conn, email)
        payload = {"login_link": f"{links.app_url}/login",
                   "reset_link": f"{links.app_url}/forgot-password"}  # fmt: skip
        queue_email(conn, "already_registered", email, payload,
                    user_id=None if existing is None else str(existing["id"]))  # fmt: skip
        return
    _send_verification(conn, links, uid, email, now)


def resend_verification(conn: Connection, links: LinkRules, email: str, now: datetime) -> None:
    """A new verification link for an unverified account; nothing otherwise (same answer)."""
    user = repository.find_user_by_email(conn, email)
    if user is not None and user["email_verified_at"] is None:
        _send_verification(conn, links, str(user["id"]), str(user["email"]), now)


def dev_verification_link(
    conn: Connection, links: LinkRules, email: str, now: datetime
) -> str | None:
    """Development only: a fresh link for an unverified account (the router checks APP_ENV)."""
    user = repository.find_user_by_email(conn, email)
    if user is None or user["email_verified_at"] is not None:
        return None
    return verification_link(conn, links, str(user["id"]), now)


def token_invalid() -> ApiError:
    """400 ``token_invalid``: unknown, used or expired link."""
    return ApiError(400, "token_invalid", "This link has expired or was already used")


def _verified(conn: Connection, user: Mapping[str, Any], now: datetime, trial: StartTrial) -> bool:
    """Mark the e-mail verified; the first time also starts the trial. Returns trial started."""
    uid = str(user["id"])
    if not repository.mark_verified(conn, uid, now):
        return False
    return trial(conn, uid, str(user["email"]), now)


def verify_email(
    conn: Connection, token: str, now: datetime, trial: StartTrial
) -> tuple[str, bool]:
    """Spend a verification token (DD 4.2 ``/auth/verify``).

    Returns:
        The user ID and whether the 15-day trial started.

    Raises:
        ApiError: 400 ``token_invalid``.
    """
    uid = repository.use_token(conn, token_hash(token), VERIFY, now)
    user = None if uid is None else repository.find_user_by_id(conn, uid)
    if user is None:
        raise token_invalid()
    return str(user["id"]), _verified(conn, user, now, trial)


def forgot_password(conn: Connection, links: LinkRules, email: str, now: datetime) -> None:
    """E-mail a reset link (1 h) to a live account; nothing otherwise (FR-ACC-03)."""
    user = repository.find_user_by_email(conn, email)
    if user is None:
        return
    uid = str(user["id"])
    token = _issue(conn, uid, RESET, links.reset_ttl, now)
    minutes = int(links.reset_ttl.total_seconds() // 60)
    queue_email(conn, "reset", str(user["email"]),
                {"link": f"{links.app_url}/reset-password?token={token}", "ttl_minutes": minutes},
                user_id=uid)  # fmt: skip


def reset_password(
    conn: Connection, token: str, new_password: str, now: datetime, trial: StartTrial
) -> tuple[str, tuple[str, ...]]:
    """Set a new password with a reset token and revoke every session (DD 4.2).

    Opening the link proves the inbox, so an unverified e-mail becomes verified (and starts the
    trial the first time).

    Returns:
        The user ID and the revoked session IDs.

    Raises:
        ApiError: 400 ``token_invalid``.
    """
    uid = repository.use_token(conn, token_hash(token), RESET, now)
    user = None if uid is None else repository.find_user_by_id(conn, uid)
    if user is None:
        raise token_invalid()
    uid = str(user["id"])
    repository.lock_user(conn, uid)
    repository.set_password(conn, uid, _hasher.hash(new_password))
    repository.retire_tokens(conn, uid, RESET, now)
    revoked = repository.revoke_all_sessions(conn, uid, now)
    _verified(conn, user, now, trial)
    return uid, tuple(revoked)


def update_profile(conn: Connection, user_id: str, fields: Mapping[str, Any]) -> dict[str, Any]:
    """Save name, timezone, trading style or billing country (FR-ACC-04); returns the user."""
    repository.update_profile(conn, user_id, dict(fields))
    user = repository.find_user_by_id(conn, user_id)
    if user is None:
        raise not_authenticated()
    return public_user(user)


def delete_account(
    conn: Connection, user_id: str, password: str, cancel_subscription: bool, now: datetime,
    billing: AccountBilling,
) -> tuple[str, ...]:  # fmt: skip
    """Delete a customer's account (FR-ACC-06, DD 4.6).

    Raises:
        ApiError: 403 ``forbidden`` for staff, 403 ``invalid_credentials`` on a wrong password,
            409 ``subscription_active`` when a paid plan is live and not confirmed cancelled.

    Returns:
        The IDs of the sessions that were live (their streams are told the session ended).
    """
    repository.lock_user(conn, user_id)
    user = repository.find_user_by_id(conn, user_id)
    if user is None:
        raise not_authenticated()
    if user["role"] != "customer":
        raise ApiError(403, "forbidden", "Staff accounts are removed by an admin")
    if not _password_ok(user["password_hash"], password):
        raise ApiError(403, "invalid_credentials", "Password is incorrect")
    if billing.paid_subscription_live(conn, user_id, now) and not cancel_subscription:
        raise ApiError(409, "subscription_active", ACTIVE_PLAN_MESSAGE)
    billing.end_subscriptions(conn, user_id, now)
    revoked = repository.revoke_all_sessions(conn, user_id, now)
    repository.purge_user(conn, user_id, now)
    return tuple(revoked)
