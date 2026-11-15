"""Sign-in, sign-out and the profile read (DD 4.2 Accounts; task 2.4: login, logout, me only).

Registration, verification, password reset and ``PATCH``/``DELETE /me`` arrive in Increment 3.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from redis.exceptions import RedisError
from sqlalchemy import Connection

from tradelens.core.config import AppConfig
from tradelens.core.deps import (
    AccountSummary,
    Viewer,
    get_account_summary,
    get_clock,
    get_config,
    get_conn,
    get_redis,
    get_viewer,
)
from tradelens.core.errors import ApiError
from tradelens.core.keys import user_channel
from tradelens.core.rate_limit import enforce
from tradelens.core.security import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    client_ip,
    csrf_token,
    origin_of,
    origin_ok,
)
from tradelens.modules.accounts.service import SessionRules, login, logout, public_user

router = APIRouter(prefix="/api/v1", tags=["accounts"])
DAY_SECONDS = 86_400


class LoginIn(BaseModel):
    """``POST /auth/login`` body."""

    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


def _rules(cfg: AppConfig) -> SessionRules:
    return SessionRules(cfg.session_secret, cfg.session_idle_days, cfg.max_sessions_per_user)


def set_session_cookies(response: Response, cfg: AppConfig, token: str, sid: str) -> None:
    """Session and CSRF cookies with a fresh 7-day ``Max-Age`` (re-issued as the session slides)."""
    age = cfg.session_idle_days * DAY_SECONDS
    response.set_cookie(SESSION_COOKIE, token, max_age=age, path="/", secure=True,
                        httponly=True, samesite="lax")  # fmt: skip
    response.set_cookie(CSRF_COOKIE, csrf_token(cfg.csrf_secret, sid), max_age=age, path="/",
                        secure=True, httponly=False, samesite="lax")  # fmt: skip


def _announce_ended(
    redis: Any,  # noqa: ANN401 - redis.Redis
    user_id: str,
    revoked: tuple[str, ...],
    reason: str = "signed_in_elsewhere",
) -> None:
    """``session.ended`` for the SSE streams of revoked sessions (DD 4.4)."""
    if not revoked:
        return
    msg = {"event": "session.ended", "data": {"reason": reason, "sessions": list(revoked)}}
    # On a Redis error the revoked cookie still answers session_ended on its next request.
    with contextlib.suppress(RedisError, OSError):
        redis.publish(user_channel(user_id), json.dumps(msg))


@router.post("/auth/login")
def post_login(
    body: LoginIn,
    request: Request,
    response: Response,
    conn: Annotated[Connection, Depends(get_conn, scope="function")],
    redis: Annotated[Any, Depends(get_redis)],  # noqa: ANN401 - redis.Redis
    cfg: Annotated[AppConfig, Depends(get_config)],
    clock: Annotated[Callable[[], datetime], Depends(get_clock)],
    summary: Annotated[AccountSummary, Depends(get_account_summary)],
) -> dict[str, Any]:
    """Sign in; sets the session and CSRF cookies; a third session ends the oldest (FR-ACC-05).

    Anonymous posts need no CSRF token but a matching ``Origin`` (DD 4.1). Attempts count
    against 5 a minute per account and 20 a minute per IP, before the password is checked.
    """
    if not origin_ok(request.headers.get("origin"), (origin_of(cfg.app_url),)):
        raise ApiError(403, "origin_mismatch", "Request origin not allowed")
    ip = client_ip(request.headers.get("x-forwarded-for"),
                   request.client.host if request.client else None)  # fmt: skip
    enforce(redis, f"login:ip:{ip}", cfg.rate_login_ip)
    enforce(redis, f"login:acct:{body.email.strip().lower()}", cfg.rate_login_account)
    result = login(conn, _rules(cfg), body.email.strip(), body.password, clock(),
                   request.headers.get("user-agent"))  # fmt: skip
    uid = str(result.user["id"])
    set_session_cookies(response, cfg, result.token, result.session_id)
    _announce_ended(redis, uid, result.revoked)
    return {"user": public_user(result.user), **summary(conn, uid)}


@router.post("/auth/logout", status_code=204)
def post_logout(
    viewer: Annotated[Viewer, Depends(get_viewer)],
    conn: Annotated[Connection, Depends(get_conn, scope="function")],
    clock: Annotated[Callable[[], datetime], Depends(get_clock)],
    redis: Annotated[Any, Depends(get_redis)],  # noqa: ANN401 - redis.Redis
) -> Response:
    """Revoke this session and clear the cookies."""
    logout(conn, viewer.session_id, clock())
    _announce_ended(redis, viewer.user_id, (viewer.session_id,), "signed_out")
    out = Response(status_code=204)
    for name in (SESSION_COOKIE, CSRF_COOKIE):
        out.delete_cookie(name, path="/", secure=True, samesite="lax")
    return out


@router.get("/me")
def get_me(
    viewer: Annotated[Viewer, Depends(get_viewer)],
    conn: Annotated[Connection, Depends(get_conn, scope="function")],
    summary: Annotated[AccountSummary, Depends(get_account_summary)],
) -> dict[str, Any]:
    """Profile, plan, entitlements and subscription (DD 4.2)."""
    user = {"id": viewer.user_id, "email": viewer.email, "name": viewer.name,
            "timezone": viewer.timezone, "trading_style": viewer.trading_style,
            "billing_country": viewer.billing_country}  # fmt: skip
    return {"user": user, **summary(conn, viewer.user_id), "unread_notifications": 0}
