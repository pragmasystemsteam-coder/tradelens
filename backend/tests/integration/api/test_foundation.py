"""API foundation: sign-in, sessions, CSRF and rate limits (DD 4.1, 7.4; task 2.4; FR-ACC-05)."""

import json
from datetime import timedelta

import pytest
from api_support import ORIGIN, PASSWORD, client, make_app, new_user, sign_in
from plans_util import plan_code, plan_name
from sqlalchemy import text

pytestmark = pytest.mark.integration


@pytest.fixture
def api(db):
    return make_app(db)


def set_cookies(response):
    return [v for k, v in response.headers.multi_items() if k.lower() == "set-cookie"]


def test_login_sets_host_cookies(db, api):
    app, _, _ = api
    email, uid = new_user(db)
    r = client(app).post("/api/v1/auth/login", json={"email": email.upper(), "password": PASSWORD})
    assert r.status_code == 200
    cookies = {c.split("=", 1)[0]: c for c in set_cookies(r)}
    session, csrf = cookies["__Host-tl_session"], cookies["__Host-tl_csrf"]
    for c in (session, csrf):
        low = c.lower()
        assert "secure" in low and "path=/" in low and "samesite=lax" in low
        assert "domain=" not in low  # __Host- cookies carry no Domain
    assert "httponly" in session.lower()
    assert "httponly" not in csrf.lower()  # the browser script reads it for X-CSRF-Token
    body = r.json()
    assert body["user"]["id"] == uid and "password_hash" not in body["user"]
    assert body["plan"]["code"] == plan_code("free")
    assert body["entitlements"]["asset_classes"] == ["forex"]
    assert body["subscription"] is None
    raw = session.split("=", 1)[1].split(";")[0]
    with db.begin() as conn:
        stored = conn.execute(text("SELECT id FROM sessions WHERE user_id = :u"), {"u": uid}).all()
    assert len(stored) == 1 and stored[0][0] != raw and len(stored[0][0]) == 64  # HMAC only


def test_wrong_password_and_unknown_email_same_answer(db, api):
    app, _, _ = api
    email, _ = new_user(db)
    a = client(app).post("/api/v1/auth/login", json={"email": email, "password": "nope-nope-1"})
    b = client(app).post("/api/v1/auth/login",
                         json={"email": "nobody@example.com", "password": "nope-nope-1"})  # fmt: skip
    assert a.status_code == b.status_code == 401
    assert a.json()["error"]["code"] == b.json()["error"]["code"] == "invalid_credentials"
    assert a.json()["error"]["message"] == b.json()["error"]["message"]


def test_third_session_revokes_oldest(db, api):
    app, clock, redis = api
    email, uid = new_user(db)
    first = sign_in(app, email)
    clock.now += timedelta(seconds=1)
    second = sign_in(app, email)
    clock.now += timedelta(seconds=1)
    third = sign_in(app, email)
    r = first.get("/api/v1/me")
    assert r.status_code == 401 and r.json()["error"]["code"] == "session_ended"
    assert second.get("/api/v1/me").status_code == 200
    assert third.get("/api/v1/me").status_code == 200
    ended = [json.loads(m) for ch, m in redis.published if ch == f"user:{uid}"]
    assert [m["event"] for m in ended] == ["session.ended"]


def test_session_idle_7d_expires(db, api):
    app, clock, _ = api
    email, _ = new_user(db)
    c = sign_in(app, email)
    clock.now += timedelta(days=6)
    assert c.get("/api/v1/me").status_code == 200  # use slides the 7-day idle window
    clock.now += timedelta(days=6)
    assert c.get("/api/v1/me").status_code == 200
    clock.now += timedelta(days=7, seconds=1)
    r = c.get("/api/v1/me")
    assert r.status_code == 401 and r.json()["error"]["code"] == "not_authenticated"


def test_csrf_required_on_post(db, api):
    app, _, _ = api
    email, _ = new_user(db)
    c = sign_in(app, email)
    token = c.headers.pop("X-CSRF-Token")
    r = c.post("/api/v1/auth/logout")
    assert r.status_code == 403 and r.json()["error"]["code"] == "csrf_failed"
    r = c.post(
        "/api/v1/auth/logout", headers={"X-CSRF-Token": token, "Origin": "https://evil.test"}
    )
    assert r.status_code == 403 and r.json()["error"]["code"] == "origin_mismatch"
    r = c.post("/api/v1/auth/logout", headers={"X-CSRF-Token": token})
    assert r.status_code == 204
    assert c.get("/api/v1/me").json()["error"]["code"] in ("session_ended", "not_authenticated")


def test_login_needs_matching_origin(db, api):
    app, _, _ = api
    email, _ = new_user(db)
    c = client(app)
    r = c.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD},
               headers={"Origin": "https://evil.test"})  # fmt: skip
    assert r.status_code == 403 and r.json()["error"]["code"] == "origin_mismatch"


def test_login_rate_limit_6th_429(db, api):
    app, _, _ = api
    email, _ = new_user(db)
    c = client(app)
    codes = [c.post("/api/v1/auth/login", json={"email": email, "password": "wrong-pass-1"})
             for _ in range(6)]  # fmt: skip
    assert [r.status_code for r in codes] == [401] * 5 + [429]
    assert codes[-1].json()["error"]["code"] == "rate_limited"
    assert 1 <= int(codes[-1].headers["Retry-After"]) <= 60


def test_me_returns_profile_plan_and_is_get_only(db, api):
    app, _, _ = api
    email, _ = new_user(db, plan="pro_monthly")
    c = sign_in(app, email)
    body = c.get("/api/v1/me").json()
    assert body["user"]["email"] == email and body["user"]["timezone"] == "UTC"
    assert body["plan"] == {"code": plan_code("pro_monthly"), "name": plan_name("Pro monthly")}
    assert body["subscription"]["status"] == "active"
    assert body["entitlements"]["mtf_detail"] == "full"
    assert body["unread_notifications"] == 0
    assert c.patch("/api/v1/me", json={"name": "x"}).status_code == 405


def test_api_rate_limit_120_per_minute(db, api):
    app, _, _ = api
    email, _ = new_user(db)
    c = sign_in(app, email)
    codes = [c.get("/api/v1/me").status_code for _ in range(121)]
    assert codes[:120] == [200] * 120 and codes[120] == 429


def test_request_id_header_and_body(db, api):
    app, _, _ = api
    r = client(app).get("/api/v1/me", headers={"X-Request-ID": "abc-123", "Origin": ORIGIN})
    assert r.status_code == 401
    assert r.headers["X-Request-ID"] == "abc-123"
    assert r.json()["error"]["request_id"] == "abc-123"


def test_session_cookie_slides_with_use(db, api):
    """Review fix: the browser cookie must not expire 7 days after login while in use."""
    app, clock, _ = api
    email, _ = new_user(db)
    c = sign_in(app, email)
    clock.now += timedelta(minutes=2)
    r = c.get("/api/v1/me")
    cookies = {v.split("=", 1)[0]: v.lower() for v in set_cookies(r)}
    assert "max-age=604800" in cookies["__Host-tl_session"]
    assert "__Host-tl_csrf" in cookies
    r = c.get("/api/v1/me")  # within the same minute: no rewrite
    assert set_cookies(r) == []


def test_logout_ends_open_streams(db, api):
    """Review fix: logout publishes session.ended for this session's SSE streams."""
    app, _, redis = api
    email, uid = new_user(db)
    c = sign_in(app, email)
    assert c.post("/api/v1/auth/logout").status_code == 204
    ended = [json.loads(m) for ch, m in redis.published if ch == f"user:{uid}"]
    assert [m["event"] for m in ended] == ["session.ended"]
    assert ended[0]["data"]["reason"] == "signed_out"
