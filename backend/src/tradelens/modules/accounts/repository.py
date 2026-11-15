"""SQL for users (DD 2.1)."""

from __future__ import annotations

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
