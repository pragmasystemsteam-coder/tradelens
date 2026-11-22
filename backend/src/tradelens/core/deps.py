"""Request dependencies shared by module routers, bound in ``app/bootstrap.py`` (ADR-0001).

Routers declare ``Depends(get_viewer)`` and friends; these placeholders only say what a
request needs. ``app.bootstrap.wire`` overrides each with the real implementation (database
connection, Redis, signed-in user), and tests override them with fakes. Nothing here imports
the web framework.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Connection

from tradelens.core.config import AppConfig
from tradelens.core.limits import Limits


class NotWiredError(RuntimeError):
    """A dependency placeholder was called without ``wire()`` binding it."""


@dataclass(frozen=True, slots=True)
class Viewer:
    """The signed-in customer of a request, with effective limits (DD 4.3).

    Attributes:
        user_id: User UUID.
        email: E-mail address.
        name: Display name.
        timezone: IANA zone for display (FR-ACC-04).
        trading_style: scalping, intraday or swing (default scanner timeframe).
        billing_country: ISO country or None.
        role: customer, support or admin.
        session_id: Stored (HMAC) session ID.
        limits: Effective limits from ``billing.entitlements``.
    """

    user_id: str
    email: str
    name: str
    timezone: str
    trading_style: str
    billing_country: str | None
    role: str
    session_id: str
    limits: Limits


# The plan, entitlements and subscription block of /me and /auth/login (billing owns it).
AccountSummary = Callable[[Connection, str], Mapping[str, Any]]


@dataclass(frozen=True, slots=True)
class AccountBilling:
    """What accounts needs from billing, which sits in a higher layer (DD 4.3, 4.6; task 3.2).

    Attributes:
        start_trial: ``(conn, user_id, email, now) -> started``: the 15-day trial, once per
            e-mail ever (``trial_claims``).
        paid_subscription_live: ``(conn, user_id, now)``: a paid plan still grants access.
        end_subscriptions: ``(conn, user_id, now)``: end every open subscription (deletion).
        forget_entitlements: ``(redis, user_id)``: drop the cached limits.
    """

    start_trial: Callable[[Connection, str, str, datetime], bool]
    paid_subscription_live: Callable[[Connection, str, datetime], bool]
    end_subscriptions: Callable[[Connection, str, datetime], None]
    forget_entitlements: Callable[[Any, str], None]


def get_account_billing() -> AccountBilling:
    """Billing hooks for sign-up, verification and deletion."""
    raise NotWiredError("get_account_billing")


def get_config() -> AppConfig:
    """The application configuration."""
    raise NotWiredError("get_config")


def get_clock() -> Callable[[], datetime]:
    """The UTC clock (frozen in tests)."""
    raise NotWiredError("get_clock")


def get_redis() -> Any:  # noqa: ANN401 - redis.Redis (sync); a fake in tests
    """The shared Redis client."""
    raise NotWiredError("get_redis")


def get_async_redis() -> Any:  # noqa: ANN401 - redis.asyncio.Redis; a fake in tests
    """The asyncio Redis client used by the SSE stream."""
    raise NotWiredError("get_async_redis")


def get_conn() -> Iterator[Connection]:
    """A database connection in a transaction for the request."""
    raise NotWiredError("get_conn")


def get_viewer() -> Viewer:
    """The signed-in customer (401 otherwise); CSRF and the API rate limit are checked."""
    raise NotWiredError("get_viewer")


def get_account_summary() -> AccountSummary:
    """Function building the plan, entitlements and subscription block for a user."""
    raise NotWiredError("get_account_summary")


def get_stream_viewer() -> Viewer:
    """Like :func:`get_viewer` but the database connection is released before streaming."""
    raise NotWiredError("get_stream_viewer")


def get_instrument_classes() -> Mapping[str, str]:
    """Instrument code to asset class (reference data, read once per process)."""
    raise NotWiredError("get_instrument_classes")
