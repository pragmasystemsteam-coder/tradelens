"""The signed-in customer of a request: session, CSRF, API rate limit and entitlements (DD 4.1).

Bound to ``core.deps.get_viewer`` by ``bootstrap.wire``. Order: session cookie (401), then on
unsafe methods ``Origin`` and ``X-CSRF-Token`` (403), then 120 requests a minute (429), then
the cached entitlements (``ent:{user_id}``, 60 s).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any

from fastapi import Depends, Request, Response
from sqlalchemy import Connection

from tradelens.core.config import AppConfig
from tradelens.core.deps import Viewer, get_clock, get_config, get_conn, get_redis
from tradelens.core.errors import ApiError, not_authenticated
from tradelens.core.rate_limit import enforce
from tradelens.core.security import (
    CSRF_HEADER,
    SESSION_COOKIE,
    UNSAFE_METHODS,
    csrf_ok,
    origin_of,
    origin_ok,
)
from tradelens.modules.accounts.public import SessionRules, resolve_session
from tradelens.modules.accounts.router import set_session_cookies
from tradelens.modules.billing.public import cached_entitlements, entitlements


def session_rules(cfg: AppConfig) -> SessionRules:
    """Session settings from the configuration."""
    return SessionRules(cfg.session_secret, cfg.session_idle_days, cfg.max_sessions_per_user)


def check_origin(request: Request, cfg: AppConfig) -> None:
    """403 ``origin_mismatch`` unless ``Origin`` is the app's own origin."""
    if not origin_ok(request.headers.get("origin"), (origin_of(cfg.app_url),)):
        raise ApiError(403, "origin_mismatch", "Request origin not allowed")


def viewer(
    request: Request,
    response: Response,
    conn: Annotated[Connection, Depends(get_conn, scope="function")],
    redis: Annotated[Any, Depends(get_redis)],  # noqa: ANN401 - redis.Redis
    cfg: Annotated[AppConfig, Depends(get_config)],
    clock: Annotated[Callable[[], datetime], Depends(get_clock)],
) -> Viewer:
    """Resolve the signed-in customer or raise the matching DD 4.1 error."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise not_authenticated()
    user, sid = resolve_session(conn, session_rules(cfg), token, clock())
    if user["session_touched"]:  # sliding 7-day idle: the browser cookie slides too
        set_session_cookies(response, cfg, token, sid)
    if request.method in UNSAFE_METHODS:
        check_origin(request, cfg)
        if not csrf_ok(cfg.csrf_secret, sid, request.headers.get(CSRF_HEADER)):
            raise ApiError(403, "csrf_failed", "Missing or wrong CSRF token")
    uid = str(user["id"])
    enforce(redis, f"api:{uid}", cfg.rate_api_user)
    limits = cached_entitlements(redis, uid, lambda: entitlements(conn, uid, clock()))
    return Viewer(user_id=uid, email=str(user["email"]), name=user["name"],
                  timezone=user["timezone"], trading_style=user["trading_style"],
                  billing_country=user["billing_country"], role=user["role"], session_id=sid,
                  limits=limits)  # fmt: skip
