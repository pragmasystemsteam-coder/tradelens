import time

import pytest
from fastapi.testclient import TestClient

from tradelens.app.main import create_app
from tradelens.modules.monitoring.router import get_checks


class FakeChecks:
    def __init__(self, db: bool, redis: bool) -> None:
        self._db, self._redis = db, redis

    def db_ok(self) -> bool:
        return self._db

    def redis_ok(self) -> bool:
        return self._redis


def client_with(db: bool, redis: bool) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_checks] = lambda: FakeChecks(db, redis)
    return TestClient(app)


def test_healthz_ok():
    response = client_with(db=True, redis=True).get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_healthz_503_when_db_down():
    response = client_with(db=False, redis=True).get("/healthz")
    assert response.status_code == 503
    assert response.json() == {"status": "error", "db": False, "redis": True}


def test_healthz_503_when_redis_down():
    response = client_with(db=True, redis=False).get("/healthz")
    assert response.status_code == 503
    assert response.json() == {"status": "error", "db": True, "redis": False}


def test_healthz_real_checks_fail_fast_without_services(monkeypatch):
    # Nothing listens on port 1: both checks must report down within the 2 s budget each.
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@127.0.0.1:1/none")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    started = time.monotonic()
    response = TestClient(create_app()).get("/healthz")
    assert response.status_code == 503
    assert response.json() == {"status": "error", "db": False, "redis": False}
    assert time.monotonic() - started < 6


@pytest.mark.parametrize("flag,status", [("false", 404), ("true", 200)])
def test_api_docs_follow_enable_flag(monkeypatch, flag, status):
    monkeypatch.setenv("ENABLE_API_DOCS", flag)
    assert TestClient(create_app()).get("/docs").status_code == status


def test_api_docs_off_when_flag_unset(monkeypatch):
    monkeypatch.delenv("ENABLE_API_DOCS", raising=False)
    client = TestClient(create_app())
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_create_app_refuses_docs_in_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ENABLE_API_DOCS", "true")
    with pytest.raises(RuntimeError, match="ENABLE_API_DOCS"):
        create_app()


def test_request_id_is_echoed():
    response = client_with(db=True, redis=True).get("/healthz", headers={"X-Request-ID": "abc-123"})
    assert response.headers["X-Request-ID"] == "abc-123"


@pytest.mark.parametrize("header", [None, "has spaces", "x" * 200])
def test_request_id_generated_when_missing_or_unsafe(header):
    headers = {"X-Request-ID": header} if header else {}
    response = client_with(db=True, redis=True).get("/healthz", headers=headers)
    generated = response.headers["X-Request-ID"]
    assert len(generated) == 32
    assert all(ch in "0123456789abcdef" for ch in generated)


class RecordingRedis:
    def __init__(self, fail: bool) -> None:
        self.fail, self.closed = fail, False

    def ping(self) -> bool:
        if self.fail:
            raise ConnectionError("down")
        return True

    def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize("fail,expected", [(False, True), (True, False)])
def test_redis_client_closed_after_check(fail, expected):
    from tradelens.modules.monitoring.service import InfraHealthChecks

    client = RecordingRedis(fail)
    checks = InfraHealthChecks("", "redis://example", redis_factory=lambda url: client)
    assert checks.redis_ok() is expected
    assert client.closed is True
