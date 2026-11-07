"""Worker wiring of the ingest job (CR-004, DD 8.1 task 1.9)."""

import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.exc import OperationalError

from tradelens.integrations.fakes.synthetic import SyntheticProvider
from tradelens.modules.market_data.public import (
    IngestService,
    InstrumentReport,
    load_instrument_specs,
)
from tradelens.worker.jobs.ingest import run_ingest_loop, run_ingest_once
from tradelens.worker.main import build_ingest_service

REPO = Path(__file__).resolve().parents[4]
NOW = datetime(2026, 11, 10, 15, 2, tzinfo=UTC)


def test_build_ingest_service_from_env():
    env = {
        "CONFIG_DIR": str(REPO / "config"),
        "MARKET_DATA_PROVIDER": "fake",
        "BACKFILL_MIN_CANDLES": "300",
    }
    service = build_ingest_service(env, clock=lambda: NOW)
    assert len(service.instruments) == 11


class Conn:
    def execution_options(self, **kw):
        self.options = kw
        return self


class FakeEngine:
    """connect() yields an autocommit-capable connection; begin() is used to mark failures."""

    def __init__(self, fail_first_connect=False):
        self.fail_first_connect, self.connects, self.begins, self.conns = (
            fail_first_connect,
            0,
            0,
            [],
        )

    @contextmanager
    def connect(self):
        self.connects += 1
        if self.fail_first_connect and self.connects == 1:
            raise OperationalError("SELECT 1", {}, Exception("db down"))
        conn = Conn()
        self.conns.append(conn)
        yield conn

    @contextmanager
    def begin(self):
        self.begins += 1
        yield Conn()


def service_with(monkeypatch, behaviour):
    specs = load_instrument_specs(REPO / "config")[:2]
    service = IngestService(SyntheticProvider(specs, lambda: NOW), specs, history_count=10)
    monkeypatch.setattr("tradelens.worker.jobs.ingest.SqlCandleStore", lambda conn: conn)
    monkeypatch.setattr(service, "ingest_instrument", behaviour)
    failed = []
    monkeypatch.setattr(
        service, "mark_failed",
        lambda store, code, now, reason: failed.append((code, reason)) or InstrumentReport(
            code, status="delayed", errors=[reason]),
    )  # fmt: skip
    return specs, service, failed


def test_db_error_on_one_instrument_does_not_stop_the_pass(monkeypatch):
    seen = []
    specs, service, failed = service_with(
        monkeypatch, lambda store, code, now: seen.append(code) or InstrumentReport(code)
    )
    reports = run_ingest_once(FakeEngine(fail_first_connect=True), service, lambda: NOW)
    assert seen == [specs[1].code]
    assert failed == [(specs[0].code, "OperationalError")]
    assert [r.status for r in reports] == ["delayed", "ok"]


def test_unexpected_error_marks_instrument_delayed_and_continues(monkeypatch):
    def behaviour(store, code, now):
        if code == "EUR_USD":
            raise ValueError("bug in one instrument")
        return InstrumentReport(code)

    specs, service, failed = service_with(monkeypatch, behaviour)
    engine = FakeEngine()
    reports = run_ingest_once(engine, service, lambda: NOW)
    assert failed == [("EUR_USD", "ValueError")]
    assert [r.instrument for r in reports] == ["EUR_USD", specs[1].code]
    assert all(c.options == {"isolation_level": "AUTOCOMMIT"} for c in engine.conns)


def test_ingest_loop_stops_when_asked():
    stop = threading.Event()
    stop.set()
    run_ingest_loop(FakeEngine(), None, lambda: NOW, stop, offset_s=2)  # returns at once
