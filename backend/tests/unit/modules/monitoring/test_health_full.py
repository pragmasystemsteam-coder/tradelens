"""GET /healthz/full (DD 4.8): heartbeat, series freshness and price stream."""

from fastapi.testclient import TestClient

from tradelens.app.main import create_app
from tradelens.modules.monitoring.router import get_checks, get_full_checks
from tradelens.modules.monitoring.service import FullReport, run_full_checks


class FakeFull:
    def __init__(self, heartbeat=3.0, series=60.0, prices=2.0, db=True, redis=True):
        self.ages = {"heartbeat": heartbeat, "series": series, "prices": prices}
        self._db, self._redis = db, redis

    def db_ok(self):
        return self._db

    def redis_ok(self):
        return self._redis

    def heartbeat_age(self):
        return self.ages["heartbeat"]

    def series_check_age(self):
        return self.ages["series"]

    def price_stream_age(self):
        return self.ages["prices"]


def client(checks):
    app = create_app()
    app.dependency_overrides[get_full_checks] = lambda: checks
    return TestClient(app)


def test_healthz_full_ok():
    response = client(FakeFull()).get("/healthz/full")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"] == {"db": True, "redis": True, "worker": True, "series": True,
                              "prices": True}  # fmt: skip


def test_healthz_full_fails_when_heartbeat_stale():
    response = client(FakeFull(heartbeat=16.0)).get("/healthz/full")
    assert response.status_code == 503
    assert response.json()["status"] == "error"
    assert response.json()["checks"]["worker"] is False


def test_healthz_full_fails_when_heartbeat_missing():
    assert client(FakeFull(heartbeat=None)).get("/healthz/full").status_code == 503


def test_healthz_full_fails_when_series_or_prices_stale():
    assert client(FakeFull(series=11 * 60.0)).get("/healthz/full").status_code == 503
    assert client(FakeFull(prices=None)).get("/healthz/full").status_code == 503
    assert client(FakeFull(db=False)).get("/healthz/full").status_code == 503


def test_full_report_thresholds():
    ok = run_full_checks(FakeFull(heartbeat=15.0, series=600.0, prices=15.0))
    assert ok == FullReport(db=True, redis=True, worker=True, series=True, prices=True)
    assert ok.ok


def test_plain_healthz_ignores_worker():
    # /healthz stays db + redis only, so a dead worker never restarts the API (DD 4.8).
    app = create_app()
    app.dependency_overrides[get_checks] = lambda: FakeFull(heartbeat=None)
    assert TestClient(app).get("/healthz").status_code == 200
