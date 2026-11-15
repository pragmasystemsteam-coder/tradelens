"""Building the API for tests: test config, frozen clock, fake Redis, users and signed-in clients.

The database is the throwaway PostgreSQL of ``scripts/test_db.py`` (``TEST_DATABASE_URL``);
Redis is ``fake_redis.FakeRedis``. Nothing here talks to a real service.
"""

import uuid
from datetime import UTC, datetime
from pathlib import Path

from argon2 import PasswordHasher
from fake_redis import AsyncFakeRedis, FakeRedis
from fastapi.testclient import TestClient
from plans_util import plan_code

from tradelens.app.bootstrap import Infra
from tradelens.app.main import create_app
from tradelens.core.config import AppConfig
from tradelens.modules.accounts.public import create_account
from tradelens.modules.billing.public import create_manual_subscription

REPO = Path(__file__).resolve().parents[2]
ORIGIN = "https://app.test"
PASSWORD = "correct horse battery"
FAST_HASH = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1)
NOW = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)


class Clock:
    def __init__(self, now=NOW):
        self.now = now

    def __call__(self):
        return self.now


def make_config(database_url="", **overrides):
    values = {
        "app_env": "test", "database_url": database_url, "redis_url": "",
        "enable_api_docs": False, "heartbeat_interval_seconds": 5, "heartbeat_ttl_seconds": 15,
        "session_secret": "s" * 32, "csrf_secret": "c" * 32, "app_url": ORIGIN,
        "config_dir": str(REPO / "config"),
    }  # fmt: skip
    values.update(overrides)
    return AppConfig(**values)


def make_app(engine, clock=None, redis=None, **overrides):
    clock = clock or Clock()
    redis = redis or FakeRedis(clock=lambda: clock().timestamp())
    infra = Infra(engine=engine, redis=redis, async_redis=AsyncFakeRedis(redis), clock=clock)
    app = create_app(make_config(**overrides), infra=infra)
    return app, clock, redis


def client(app):
    return TestClient(app, base_url="https://testserver", headers={"Origin": ORIGIN})


def new_user(engine, plan=None, email=None):
    """A verified customer (manual subscription when ``plan`` is given); returns the e-mail."""
    email = email or f"u{uuid.uuid4().hex[:12]}@example.com"
    with engine.begin() as conn:
        uid = create_account(conn, email, "customer", FAST_HASH.hash(PASSWORD))
        if plan is not None:
            create_manual_subscription(conn, uid, plan_code(plan))
    return email, uid


def sign_in(app, email, password=PASSWORD):
    """A client with the session cookie and the CSRF header set."""
    c = client(app)
    r = c.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    c.headers["X-CSRF-Token"] = c.cookies.get("__Host-tl_csrf")
    return c
