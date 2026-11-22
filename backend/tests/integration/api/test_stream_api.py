"""``GET /stream`` over HTTP: auth, refused topics, the 6-stream cap and headers (task 2.8).

The forwarding, throttling and heartbeat rules are unit-tested in
backend/tests/unit/modules/realtime/test_stream.py.
"""

import time

import pytest
from api_support import client, make_app, new_user, sign_in

pytestmark = pytest.mark.integration


def test_stream_needs_a_session(db):
    app, _, _ = make_app(db)
    r = client(app).get("/api/v1/stream")
    assert r.status_code == 401 and r.json()["error"]["code"] == "not_authenticated"


def test_commodity_topic_refused_free_over_http(db):
    app, _, redis = make_app(db)
    email, uid = new_user(db)
    r = sign_in(app, email).get("/api/v1/stream", params={"topics": "scanner,price:XAU_USD"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "plan_required"
    assert redis.get(f"sse:slots:{uid}") is None  # no slot taken for a refused stream


def test_bad_topic_400(db):
    app, _, _ = make_app(db)
    email, _ = new_user(db)
    r = sign_in(app, email).get("/api/v1/stream", params={"topics": "chart:NOPE"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "validation_error"


def test_seventh_stream_429(db):
    app, _, redis = make_app(db)
    email, uid = new_user(db)
    c = sign_in(app, email)
    now = time.time()  # the API scores slots with the real clock
    redis.zadd(f"sse:slots:{uid}", {f"open{i}": now for i in range(6)})  # six live streams
    r = c.get("/api/v1/stream", params={"topics": "scanner"})
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"
    assert redis.zcard(f"sse:slots:{uid}") == 6


def test_stream_opens_with_headers_and_retry(db):
    app, _, redis = make_app(db, sse_ping_seconds=25)
    email, uid = new_user(db)
    c = sign_in(app, email)
    with c.stream("GET", "/api/v1/stream", params={"topics": "scanner,chart:EUR_USD"}) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        assert r.headers["cache-control"] == "no-cache"
        assert r.headers["x-accel-buffering"] == "no"
        first = next(r.iter_text())
        assert first.startswith("retry: 3000")
        assert redis.zcard(f"sse:slots:{uid}") == 1
