"""Session tokens, CSRF tokens and Origin checks (DD 4.1; AD-09).

A session cookie holds a random 256-bit value; the database stores only
``HMAC(SESSION_SECRET, value)``, so a leaked table cannot be replayed. The CSRF cookie is
``HMAC(CSRF_SECRET, session id)`` and must come back in ``X-CSRF-Token``.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from urllib.parse import urlsplit

SESSION_COOKIE = "__Host-tl_session"
CSRF_COOKIE = "__Host-tl_csrf"
CSRF_HEADER = "X-CSRF-Token"
TOKEN_BYTES = 32  # 256 bits
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _mac(secret: str, value: str) -> str:
    return hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def new_session_token() -> str:
    """A fresh random session value for the cookie (URL-safe)."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def session_id(secret: str, token: str) -> str:
    """The stored session ID for a cookie value."""
    return _mac(secret, token)


def csrf_token(secret: str, sid: str) -> str:
    """The CSRF token bound to a stored session ID."""
    return _mac(secret, f"csrf:{sid}")


def csrf_ok(secret: str, sid: str, header: str | None) -> bool:
    """Constant-time check of ``X-CSRF-Token``."""
    if not header or not header.isascii():
        return False  # a latin-1 header would make compare_digest raise TypeError
    return hmac.compare_digest(csrf_token(secret, sid).encode(), header.encode())


def origin_of(url: str) -> str:
    """``scheme://host[:port]`` of a URL ('' when it has no host)."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}" if parts.scheme and parts.netloc else ""


def origin_ok(origin: str | None, allowed: tuple[str, ...]) -> bool:
    """Whether the ``Origin`` header names one of the allowed origins exactly."""
    return bool(origin) and origin_of(str(origin)) in allowed


def client_ip(forwarded_for: str | None, peer: str | None) -> str:
    """The caller's IP for rate limits.

    Caddy (the only way in) overwrites ``X-Forwarded-For`` with the client IP it resolved
    (``CF-Connecting-IP`` from a Cloudflare peer, else the peer address; deploy/Caddyfile),
    so the header holds exactly one trusted address.
    """
    if forwarded_for:
        first = forwarded_for.split(",")[0].strip()
        if first:
            return first
    return peer or "unknown"
