"""Sign-up, verification, trial, password reset, profile and deletion (DD 4.2, 4.3, 4.6; task 3.2).

E-mails are read back from ``email_outbox`` (the worker is not running in these tests).
"""

import json
import uuid
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from api_support import ORIGIN, PASSWORD, client, make_app, new_user, sign_in
from plans_util import plan_code
from sqlalchemy import text

pytestmark = pytest.mark.integration

NEW_PASSWORD = "a much longer passphrase"
STRONG = {"session_secret": "a" * 64, "csrf_secret": "b" * 64}


@pytest.fixture
def api(db):
    return make_app(db)


def fresh_email(tag="s"):
    return f"{tag}{uuid.uuid4().hex[:12]}@example.com"


def mails(db, email, kind=None):
    sql = "SELECT kind, subject, payload, user_id FROM email_outbox WHERE to_email = :e"
    if kind:
        sql += " AND kind = :k"
    with db.begin() as conn:
        rows = conn.execute(text(sql + " ORDER BY id"), {"e": email, "k": kind}).mappings().all()
    return [dict(r) for r in rows]


def token_of(mail):
    return parse_qs(urlparse(mail["payload"]["link"]).query)["token"][0]


def register(app, email, password=PASSWORD, **extra):
    return client(app).post("/api/v1/auth/register",
                            json={"email": email, "password": password, **extra})  # fmt: skip


def verify(app, token):
    return client(app).post("/api/v1/auth/verify", json={"token": token})


def signed_up(app, db, email=None, **extra):
    """Register and verify; returns the e-mail."""
    email = email or fresh_email()
    assert register(app, email, **extra).status_code == 202
    assert verify(app, token_of(mails(db, email, "verify")[-1])).status_code == 200
    return email


def user_row(db, email):
    with db.begin() as conn:
        row = conn.execute(text("SELECT * FROM users WHERE email = :e AND deleted_at IS NULL"),
                           {"e": email}).mappings().first()  # fmt: skip
    return None if row is None else dict(row)


# ---------------------------------------------------------------- register


def test_register_always_202(db, api):
    """New and existing e-mails get the same answer; the existing one gets an
    "already registered" mail and no second account (no enumeration, FR-ACC-01)."""
    app, _, _ = api
    new = fresh_email()
    existing, _ = new_user(db)
    a = register(app, new)
    b = register(app, existing.upper())
    assert a.status_code == b.status_code == 202
    assert a.json() == b.json() == {"status": "verification_sent"}
    assert [m["kind"] for m in mails(db, new)] == ["verify"]
    assert [m["kind"] for m in mails(db, existing)] == ["already_registered"]
    with db.begin() as conn:
        n = conn.execute(text("SELECT count(*) FROM users WHERE email = :e"), {"e": existing})
        assert n.scalar() == 1
    row = user_row(db, new)
    assert row["email_verified_at"] is None and row["password_hash"].startswith("$argon2id$")


def test_register_existing_unverified_gets_already_registered(db, api):
    app, _, _ = api
    email = fresh_email()
    register(app, email)
    register(app, email, password="another password 1")
    assert [m["kind"] for m in mails(db, email)] == ["verify", "already_registered"]


def test_register_saves_profile_fields(db, api):
    app, _, _ = api
    email = fresh_email()
    r = register(app, email, name="Asha", timezone="Asia/Kolkata", trading_style="swing")
    assert r.status_code == 202
    row = user_row(db, email)
    assert (row["name"], row["timezone"], row["trading_style"]) == ("Asha", "Asia/Kolkata", "swing")


@pytest.mark.parametrize("body", [
    {"password": "short"},
    {"email": "not-an-email"},
    {"timezone": "Mars/Base"},
    {"trading_style": "hodl"},
    {"is_admin": True},
])  # fmt: skip
def test_register_validation(db, api, body):
    app, _, _ = api
    payload = {"email": fresh_email(), "password": PASSWORD, **body}
    r = client(app).post("/api/v1/auth/register", json=payload)
    assert r.status_code == 400 and r.json()["error"]["code"] == "validation_error"


def test_anonymous_posts_need_origin_and_json(db, api):
    app, _, _ = api
    c = client(app)
    del c.headers["Origin"]
    r = c.post("/api/v1/auth/register", json={"email": fresh_email(), "password": PASSWORD})
    assert r.status_code == 403 and r.json()["error"]["code"] == "origin_mismatch"
    r = client(app).post("/api/v1/auth/register", content=f"email={fresh_email()}",
                         headers={"Content-Type": "application/x-www-form-urlencoded"})  # fmt: skip
    assert r.status_code == 415 and r.json()["error"]["code"] == "json_required"
    for path in ("/auth/verify", "/auth/verify/resend", "/auth/password/forgot",
                 "/auth/password/reset"):  # fmt: skip
        r = client(app).post("/api/v1" + path, content="x", headers={"Content-Type": "text/plain"})
        assert r.status_code == 415, path


def test_anonymous_rate_limit_5_per_min_per_ip(db, api):
    app, clock, _ = api
    codes = [register(app, fresh_email()).status_code for _ in range(6)]
    assert codes == [202] * 5 + [429]
    r = client(app).post("/api/v1/auth/password/forgot", json={"email": fresh_email()})
    assert r.status_code == 429  # register, resend and forgot share the 5/min budget
    clock.now += timedelta(seconds=61)
    assert register(app, fresh_email()).status_code == 202


# ---------------------------------------------------------------- verify and sign-in


def test_unverified_cannot_login(db, api):
    app, _, _ = api
    email = fresh_email()
    register(app, email)
    r = client(app).post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 403 and r.json()["error"]["code"] == "email_not_verified"


def test_verify_link_expires_24h(db, api):
    app, clock, _ = api
    late, ok = fresh_email(), fresh_email()
    register(app, late)
    register(app, ok)
    clock.now += timedelta(hours=24) - timedelta(seconds=1)
    assert verify(app, token_of(mails(db, ok)[0])).status_code == 200
    clock.now += timedelta(seconds=2)
    r = verify(app, token_of(mails(db, late)[0]))
    assert r.status_code == 400 and r.json()["error"]["code"] == "token_invalid"
    assert user_row(db, late)["email_verified_at"] is None


def test_verify_token_single_use_and_unknown(db, api):
    app, _, _ = api
    email = fresh_email()
    register(app, email)
    token = token_of(mails(db, email)[0])
    assert verify(app, token).status_code == 200
    again = verify(app, token)
    assert again.status_code == 400 and again.json()["error"]["code"] == "token_invalid"
    assert verify(app, "x" * 43).json()["error"]["code"] == "token_invalid"
    with db.begin() as conn:  # only the SHA-256 of the token is stored
        stored = conn.execute(text("SELECT token_hash FROM email_tokens WHERE user_id = :u"),
                              {"u": user_row(db, email)["id"]}).scalars().all()  # fmt: skip
    assert token not in stored and all(len(h) == 64 for h in stored)


def test_verify_starts_trial_15_days(db, api):
    app, clock, _ = api
    email = fresh_email()
    register(app, email)
    r = verify(app, token_of(mails(db, email)[0]))
    assert r.status_code == 200 and r.json() == {"status": "verified", "trial_started": True}
    body = sign_in(app, email).get("/api/v1/me").json()
    assert body["plan"]["code"] == plan_code("pro_monthly")
    assert body["subscription"]["status"] == "trialing"
    expected = (clock.now + timedelta(days=15)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert body["subscription"]["trial_ends_at"] == expected
    assert "metal" in body["entitlements"]["asset_classes"]
    with db.begin() as conn:
        sub = conn.execute(text("SELECT source FROM subscriptions WHERE user_id = :u"),
                           {"u": body["user"]["id"]}).scalar()  # fmt: skip
    assert sub == "trial"


def test_trial_ends_after_15_days(db, api):
    app, clock, _ = api
    email = signed_up(app, db)
    clock.now += timedelta(days=15, seconds=1)
    body = sign_in(app, email).get("/api/v1/me").json()
    assert body["plan"]["code"] == plan_code("free")


def test_second_trial_same_email_refused(db, api):
    """One trial per e-mail ever, also after deleting the account (DD 4.3, 4.6)."""
    app, _, _ = api
    email = signed_up(app, db)
    c = sign_in(app, email)
    assert c.request("DELETE", "/api/v1/me", json={"password": PASSWORD}).status_code == 204
    assert register(app, email.upper()).status_code == 202  # the hash is of the lower-cased e-mail
    r = verify(app, token_of(mails(db, email, "verify")[-1]))
    assert r.status_code == 200 and r.json()["trial_started"] is False
    body = sign_in(app, email).get("/api/v1/me").json()
    assert body["plan"]["code"] == plan_code("free") and body["subscription"] is None


def test_resend_issues_new_link_and_is_quiet(db, api):
    app, _, _ = api
    email = fresh_email()
    register(app, email)
    first = token_of(mails(db, email)[0])
    r = client(app).post("/api/v1/auth/verify/resend", json={"email": email})
    assert r.status_code == 202 and r.json() == {"status": "verification_sent"}
    second = token_of(mails(db, email, "verify")[-1])
    assert first != second
    assert verify(app, first).status_code == 400  # the older link stops working
    assert verify(app, second).status_code == 200
    unknown = fresh_email()
    for who in (email, unknown):  # verified, then unknown: same answer, no mail
        r = client(app).post("/api/v1/auth/verify/resend", json={"email": who})
        assert r.status_code == 202 and r.json() == {"status": "verification_sent"}
    assert len(mails(db, email, "verify")) == 2 and mails(db, unknown) == []


# ---------------------------------------------------------------- password reset


def forgot(app, email):
    return client(app).post("/api/v1/auth/password/forgot", json={"email": email})


def reset(app, token, password=NEW_PASSWORD):
    return client(app).post("/api/v1/auth/password/reset",
                            json={"token": token, "new_password": password})  # fmt: skip


def test_forgot_same_answer_for_unknown_email(db, api):
    app, _, _ = api
    email, _ = new_user(db)
    a, b = forgot(app, email), forgot(app, fresh_email())
    assert a.status_code == b.status_code == 202 and a.json() == b.json()
    assert [m["kind"] for m in mails(db, email)] == ["reset"]


def test_reset_single_use_1h(db, api):
    app, clock, _ = api
    email, _ = new_user(db)
    forgot(app, email)
    token = token_of(mails(db, email, "reset")[-1])
    assert reset(app, token).status_code == 204
    again = reset(app, token, "yet another password")
    assert again.status_code == 400 and again.json()["error"]["code"] == "token_invalid"
    sign_in(app, email, NEW_PASSWORD)
    old = client(app).post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert old.status_code == 401
    forgot(app, email)
    late = token_of(mails(db, email, "reset")[-1])
    clock.now += timedelta(hours=1, seconds=1)
    assert reset(app, late).json()["error"]["code"] == "token_invalid"


def test_reset_password_min_length(db, api):
    app, _, _ = api
    email, _ = new_user(db)
    forgot(app, email)
    r = reset(app, token_of(mails(db, email, "reset")[-1]), "short")
    assert r.status_code == 400 and r.json()["error"]["code"] == "validation_error"


def test_reset_revokes_sessions(db, api):
    app, clock, redis = api
    email, uid = new_user(db)
    first = sign_in(app, email)
    clock.now += timedelta(seconds=1)
    second = sign_in(app, email)
    forgot(app, email)
    assert reset(app, token_of(mails(db, email, "reset")[-1])).status_code == 204
    for c in (first, second):
        r = c.get("/api/v1/me")
        assert r.status_code == 401 and r.json()["error"]["code"] == "session_ended"
    ended = [json.loads(m) for ch, m in redis.published if ch == f"user:{uid}"]
    assert ended[-1]["event"] == "session.ended"
    assert ended[-1]["data"]["reason"] == "password_reset"


def test_reset_verifies_an_unverified_email(db, api):
    app, _, _ = api
    email = fresh_email()
    register(app, email)
    forgot(app, email)
    assert reset(app, token_of(mails(db, email, "reset")[-1])).status_code == 204
    body = sign_in(app, email, NEW_PASSWORD).get("/api/v1/me").json()
    assert body["subscription"]["status"] == "trialing"  # proving the inbox starts the trial


# ---------------------------------------------------------------- profile


def test_timezone_saved(db, api):
    app, _, _ = api
    email, _ = new_user(db)
    c = sign_in(app, email)
    r = c.patch("/api/v1/me", json={"timezone": "Asia/Kolkata", "name": "Ravi",
                                    "trading_style": "scalping", "billing_country": "IN"})  # fmt: skip
    assert r.status_code == 200
    user = c.get("/api/v1/me").json()["user"]
    assert (user["timezone"], user["name"], user["trading_style"], user["billing_country"]) == (
        "Asia/Kolkata", "Ravi", "scalping", "IN")  # fmt: skip
    bad = c.patch("/api/v1/me", json={"timezone": "Nowhere/City"})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "validation_error"
    assert c.patch("/api/v1/me", json={"email": "x@example.com"}).status_code == 400


def test_patch_me_needs_csrf(db, api):
    app, _, _ = api
    email, _ = new_user(db)
    c = sign_in(app, email)
    del c.headers["X-CSRF-Token"]
    assert c.patch("/api/v1/me", json={"name": "x"}).json()["error"]["code"] == "csrf_failed"


# ---------------------------------------------------------------- deletion


def test_delete_keeps_billing_and_frees_email(db, api):
    app, _, _ = api
    email = signed_up(app, db)
    c = sign_in(app, email)
    uid = c.get("/api/v1/me").json()["user"]["id"]
    assert c.post("/api/v1/watchlists", json={"name": "Majors"}).status_code == 201
    r = c.request("DELETE", "/api/v1/me", json={"password": PASSWORD})
    assert r.status_code == 204
    assert c.get("/api/v1/me").status_code == 401
    with db.begin() as conn:
        user = conn.execute(text("SELECT * FROM users WHERE id = :u"), {"u": uid}).mappings().one()
        subs = conn.execute(text("SELECT status FROM subscriptions WHERE user_id = :u"),
                            {"u": uid}).scalars().all()  # fmt: skip
        left = {}
        for t in ("sessions", "email_tokens", "watchlists", "notifications"):
            sql = text(f"SELECT count(*) FROM {t} WHERE user_id = :u")
            left[t] = conn.execute(sql, {"u": uid}).scalar()
        claims = conn.execute(text("SELECT count(*) FROM trial_claims WHERE user_id = :u"),
                              {"u": uid}).scalar()  # fmt: skip
    assert user["deleted_at"] is not None
    assert user["email"] == f"deleted+{uid}@invalid"
    assert user["name"] == "" and user["password_hash"] == "" and user["totp_secret_enc"] is None
    assert subs == ["expired"]  # billing history stays (DR-03)
    assert left == {"sessions": 0, "email_tokens": 0, "watchlists": 0, "notifications": 0}
    assert claims == 1  # the trial claim survives deletion
    assert register(app, email).status_code == 202
    assert [m["kind"] for m in mails(db, email)][-1] == "verify"  # free to register again


def test_delete_with_paid_subscription_409(db, api):
    app, _, _ = api
    email, uid = new_user(db, plan="pro_monthly")
    c = sign_in(app, email)
    r = c.request("DELETE", "/api/v1/me", json={"password": PASSWORD})
    assert r.status_code == 409 and r.json()["error"]["code"] == "subscription_active"
    r = c.request("DELETE", "/api/v1/me", json={"password": PASSWORD, "cancel_subscription": True})
    assert r.status_code == 204
    with db.begin() as conn:
        status = conn.execute(text("SELECT status FROM subscriptions WHERE user_id = :u"),
                              {"u": uid}).scalar()  # fmt: skip
    assert status == "cancelled"


def test_delete_needs_password_and_refuses_staff(db, api):
    app, _, _ = api
    email, _ = new_user(db)
    c = sign_in(app, email)
    r = c.request("DELETE", "/api/v1/me", json={"password": "wrong password 1"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "invalid_credentials"
    assert c.get("/api/v1/me").status_code == 200
    staff, sid = new_user(db)
    with db.begin() as conn:
        conn.execute(text("UPDATE users SET role = 'support' WHERE id = :u"), {"u": sid})
    s = sign_in(app, staff)
    r = s.request("DELETE", "/api/v1/me", json={"password": PASSWORD})
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"


# ---------------------------------------------------------------- development verification link


def dev_link(app, email):
    return client(app).post("/api/v1/dev/verification-link", json={"email": email})


def test_dev_verification_link_only_in_development(db):
    dev, _, _ = make_app(db, app_env="development")
    email = fresh_email()
    register(dev, email)
    r = dev_link(dev, email)
    assert r.status_code == 200
    link = r.json()["link"]
    assert link.startswith(ORIGIN + "/verify-email?token=")
    assert verify(dev, parse_qs(urlparse(link).query)["token"][0]).status_code == 200
    assert dev_link(dev, email).status_code == 404  # verified: nothing to open
    assert dev_link(dev, fresh_email()).status_code == 404
    for env in ("production", "staging", "test"):
        app, _, _ = make_app(db, app_env=env, **STRONG)
        other = fresh_email()
        register(app, other)
        assert dev_link(app, other).status_code == 404, env


def test_dev_verification_link_refuses_production_even_if_mounted(db):
    """The handler checks APP_ENV itself, so mounting it by mistake still answers 404."""
    from tradelens.modules.accounts.router import dev_router

    app, _, _ = make_app(db, app_env="production", **STRONG)
    app.include_router(dev_router)
    email = fresh_email()
    register(app, email)
    assert dev_link(app, email).status_code == 404
