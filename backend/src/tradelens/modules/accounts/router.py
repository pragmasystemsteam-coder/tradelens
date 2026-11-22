"""Accounts endpoints (DD 4.2 Accounts).

Sign-in, sign-out and ``/me`` arrived in task 2.4; sign-up, verification, password reset,
``PATCH /me`` and ``DELETE /me`` in task 3.2.

Anonymous posts carry no CSRF token but must be JSON from the app's own origin (DD 4.1).
"""

from __future__ import annotations

import contextlib
import json
import zoneinfo
from collections.abc import Callable
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from redis.exceptions import RedisError
from sqlalchemy import Connection

from tradelens.core.config import AppConfig
from tradelens.core.deps import (
    AccountBilling,
    AccountSummary,
    Viewer,
    get_account_billing,
    get_account_summary,
    get_clock,
    get_config,
    get_conn,
    get_redis,
    get_viewer,
)
from tradelens.core.errors import ApiError, not_found
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
from tradelens.modules.accounts.service import (
    EMAIL,
    LinkRules,
    SessionRules,
    delete_account,
    dev_verification_link,
    forgot_password,
    login,
    logout,
    public_user,
    register,
    resend_verification,
    reset_password,
    update_profile,
    verify_email,
)

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


# ---------------------------------------------------------------- sign-up and recovery (task 3.2)
TradingStyle = Literal["scalping", "intraday", "swing"]
SENT = {"status": "verification_sent"}


@lru_cache(maxsize=1)
def _zones() -> frozenset[str]:
    return frozenset(zoneinfo.available_timezones())


def _check_timezone(value: str | None) -> str | None:
    if value is not None and value not in _zones():
        raise ValueError("not an IANA time zone")
    return value


def _check_email(value: str) -> str:
    value = value.strip()
    if not EMAIL.match(value):
        raise ValueError("not an email address")
    return value


class RegisterIn(BaseModel):
    """``POST /auth/register`` body (FR-ACC-01)."""

    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=10, max_length=256)
    name: str = Field(default="", max_length=100)
    timezone: str = "UTC"
    trading_style: TradingStyle = "intraday"

    _email = field_validator("email")(_check_email)
    _tz = field_validator("timezone")(_check_timezone)


class EmailIn(BaseModel):
    """A body with only an e-mail (resend, forgot)."""

    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=254)

    _email = field_validator("email")(_check_email)


class TokenIn(BaseModel):
    """``POST /auth/verify`` body."""

    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=1, max_length=200)


class ResetIn(BaseModel):
    """``POST /auth/password/reset`` body."""

    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=10, max_length=256)


class ProfileIn(BaseModel):
    """``PATCH /me`` body (FR-ACC-04); omitted fields are left as they are."""

    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, max_length=100)
    timezone: str | None = None
    trading_style: TradingStyle | None = None
    billing_country: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")

    _tz = field_validator("timezone")(_check_timezone)


class DeleteIn(BaseModel):
    """``DELETE /me`` body (FR-ACC-06)."""

    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=1, max_length=256)
    cancel_subscription: bool = False


def _links(cfg: AppConfig) -> LinkRules:
    return LinkRules(cfg.app_url.rstrip("/"), timedelta(hours=cfg.email_verify_ttl_hours),
                     timedelta(minutes=cfg.password_reset_ttl_minutes))  # fmt: skip


def anonymous_post(request: Request, cfg: Annotated[AppConfig, Depends(get_config)]) -> str:
    """Anonymous auth posts: no CSRF token, but JSON and the app's ``Origin`` (DD 4.1).

    Runs before the body is read. Returns the client IP for the rate limits.
    """
    if not origin_ok(request.headers.get("origin"), (origin_of(cfg.app_url),)):
        raise ApiError(403, "origin_mismatch", "Request origin not allowed")
    ctype = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if ctype != "application/json":
        raise ApiError(415, "json_required", "Send the request body as JSON")
    return client_ip(request.headers.get("x-forwarded-for"),
                     request.client.host if request.client else None)  # fmt: skip


AnonIp = Annotated[str, Depends(anonymous_post)]
Conn = Annotated[Connection, Depends(get_conn, scope="function")]
Redis = Annotated[Any, Depends(get_redis)]
Config = Annotated[AppConfig, Depends(get_config)]
Clock = Annotated[Callable[[], datetime], Depends(get_clock)]
Billing = Annotated[AccountBilling, Depends(get_account_billing)]


@router.post("/auth/register", status_code=202)
def post_register(body: RegisterIn, ip: AnonIp, conn: Conn, redis: Redis, cfg: Config,
                  clock: Clock) -> dict[str, str]:  # fmt: skip
    """Create an account and e-mail the link; always 202 (no account enumeration)."""
    enforce(redis, f"anon:ip:{ip}", cfg.rate_anon_ip)
    register(conn, _links(cfg), body.email, body.password, clock(), name=body.name.strip(),
             timezone=body.timezone, trading_style=body.trading_style)  # fmt: skip
    return SENT


@router.post("/auth/verify/resend", status_code=202)
def post_resend(body: EmailIn, ip: AnonIp, conn: Conn, redis: Redis, cfg: Config,
                clock: Clock) -> dict[str, str]:  # fmt: skip
    """A new verification link when the account is unverified; always 202."""
    enforce(redis, f"anon:ip:{ip}", cfg.rate_anon_ip)
    resend_verification(conn, _links(cfg), body.email, clock())
    return SENT


@router.post("/auth/verify")
def post_verify(body: TokenIn, ip: AnonIp, conn: Conn, redis: Redis, cfg: Config,
                clock: Clock, billing: Billing) -> dict[str, Any]:  # fmt: skip
    """Verify the e-mail (24 h link); the first verification starts the 15-day trial."""
    enforce(redis, f"token:ip:{ip}", cfg.rate_login_ip)
    uid, started = verify_email(conn, body.token, clock(), billing.start_trial)
    with contextlib.suppress(RedisError, OSError):
        billing.forget_entitlements(redis, uid)
    return {"status": "verified", "trial_started": started}


@router.post("/auth/password/forgot", status_code=202)
def post_forgot(body: EmailIn, ip: AnonIp, conn: Conn, redis: Redis, cfg: Config,
                clock: Clock) -> dict[str, str]:  # fmt: skip
    """E-mail a reset link (1 h) when the account exists; always 202 (FR-ACC-03)."""
    enforce(redis, f"anon:ip:{ip}", cfg.rate_anon_ip)
    forgot_password(conn, _links(cfg), body.email, clock())
    return {"status": "reset_sent"}


@router.post("/auth/password/reset", status_code=204)
def post_reset(body: ResetIn, ip: AnonIp, conn: Conn, redis: Redis, cfg: Config,
               clock: Clock, billing: Billing) -> Response:  # fmt: skip
    """Set a new password; every session of the account is revoked."""
    enforce(redis, f"token:ip:{ip}", cfg.rate_login_ip)
    uid, revoked = reset_password(conn, body.token, body.new_password, clock(),
                                  billing.start_trial)  # fmt: skip
    _announce_ended(redis, uid, revoked, "password_reset")
    with contextlib.suppress(RedisError, OSError):
        billing.forget_entitlements(redis, uid)
    return Response(status_code=204)


@router.patch("/me")
def patch_me(body: ProfileIn, viewer: Annotated[Viewer, Depends(get_viewer)],
             conn: Conn) -> dict[str, Any]:  # fmt: skip
    """Update name, timezone, trading style or billing country (FR-ACC-04)."""
    fields = body.model_dump(exclude_unset=True, exclude_none=True)
    if "name" in fields:
        fields["name"] = fields["name"].strip()
    return {"user": update_profile(conn, viewer.user_id, fields)}


@router.delete("/me", status_code=204)
def delete_me(body: DeleteIn, viewer: Annotated[Viewer, Depends(get_viewer)], conn: Conn,
              redis: Redis, clock: Clock, billing: Billing) -> Response:  # fmt: skip
    """Delete the account (password needed; a live paid plan must be confirmed cancelled)."""
    revoked = delete_account(conn, viewer.user_id, body.password, body.cancel_subscription,
                             clock(), billing)  # fmt: skip
    _announce_ended(redis, viewer.user_id, revoked, "account_deleted")
    with contextlib.suppress(RedisError, OSError):
        billing.forget_entitlements(redis, viewer.user_id)
    out = Response(status_code=204)
    for name in (SESSION_COOKIE, CSRF_COOKIE):
        out.delete_cookie(name, path="/", secure=True, samesite="lax")
    return out


# ---------------------------------------------------------------- development only
# Mounted only when APP_ENV=development (app.routers.DEV_ROUTERS), and the handler checks
# APP_ENV again, so a production stack can never hand out a verification link.
dev_router = APIRouter(prefix="/api/v1/dev", tags=["dev"])
DEVELOPMENT = "development"


@dev_router.post("/verification-link")
def post_dev_verification_link(body: EmailIn, ip: AnonIp, conn: Conn, redis: Redis,
                               cfg: Config, clock: Clock) -> dict[str, str]:  # fmt: skip
    """A fresh verification link for an unverified account, so a demo needs no mailbox."""
    if cfg.app_env != DEVELOPMENT:
        raise not_found()
    enforce(redis, f"anon:ip:{ip}", cfg.rate_anon_ip)
    link = dev_verification_link(conn, _links(cfg), body.email, clock())
    if link is None:
        raise not_found("No unverified account with this email")
    return {"link": link}
