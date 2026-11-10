"""Accounts: users (DD 2.1).

Day 4 only creates users for ``create-user``; sign-up, sign-in, sessions and verification
arrive in tasks 2.4 and 3.x.
"""

from __future__ import annotations

import re

from sqlalchemy import Connection

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
