"""Ingest against a real PostgreSQL 16: all 55 series fill from the fake provider (CR-004)."""

import os
from datetime import UTC, datetime, timedelta

import pytest

pytestmark = pytest.mark.integration

URL = os.environ.get("TEST_DATABASE_URL")
if not URL:
    pytest.skip("TEST_DATABASE_URL not set (needs PostgreSQL)", allow_module_level=True)

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from tradelens.cli.seed import seed  # noqa: E402
from tradelens.integrations.fakes.synthetic import SyntheticProvider  # noqa: E402
from tradelens.modules.market_data.public import (  # noqa: E402
    IngestService,
    SqlCandleStore,
    load_instrument_specs,
)
from tradelens.worker.jobs.ingest import run_ingest_once  # noqa: E402

NOW = datetime(2026, 11, 10, 15, 2, tzinfo=UTC)


@pytest.fixture(scope="module")
def engine(request):
    repo = request.config.rootpath
    cfg = Config(str(repo / "backend" / "alembic.ini"))
    cfg.set_main_option("script_location", str(repo / "backend" / "migrations"))
    previous = os.environ.get("DATABASE_MIGRATION_URL")
    os.environ["DATABASE_MIGRATION_URL"] = URL
    try:
        command.downgrade(cfg, "base")
        command.upgrade(cfg, "head")
    finally:
        if previous is None:
            os.environ.pop("DATABASE_MIGRATION_URL", None)
        else:
            os.environ["DATABASE_MIGRATION_URL"] = previous
    eng = create_engine(URL)
    with eng.begin() as conn:
        seed(conn, repo / "config")
    yield eng
    eng.dispose()


@pytest.fixture(scope="module")
def specs(request):
    return load_instrument_specs(request.config.rootpath / "config")


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


def test_all_55_series_ok_with_fake_provider(engine, specs):
    clock = Clock(NOW)
    service = IngestService(SyntheticProvider(specs, clock), specs, history_count=300)
    reports = run_ingest_once(engine, service, clock)
    assert len(reports) == 11
    assert all(r.status == "ok" and not r.errors for r in reports)
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT instrument, timeframe, status, last_candle_time FROM series_status")
        ).all()
        assert len(rows) == 55
        assert {r.status for r in rows} == {"ok"}
        assert all(r.last_candle_time is not None for r in rows)
        forming = conn.execute(
            text(
                "SELECT count(*) FROM candles WHERE open_time + CASE timeframe"
                " WHEN '5m' THEN interval '5 min' WHEN '15m' THEN interval '15 min'"
                " WHEN '1h' THEN interval '1 hour' WHEN '4h' THEN interval '4 hours'"
                " ELSE interval '1 day' END > :now"
            ),
            {"now": NOW},
        ).scalar()
        assert forming == 0
        sources = {r[0] for r in conn.execute(text("SELECT DISTINCT source FROM candles"))}
        assert sources == {"fake"}


def test_restart_continues_without_refetching_history(engine, specs):
    clock = Clock(NOW + timedelta(minutes=5))
    calls = []

    class Counting(SyntheticProvider):
        def fetch(self, instrument, timeframe, **kw):
            calls.append((instrument, timeframe))
            return super().fetch(instrument, timeframe, **kw)

    service = IngestService(Counting(specs, clock), specs, history_count=300)
    run_ingest_once(engine, service, clock)
    assert sorted({tf for _, tf in calls}) == ["5m"]  # history is cached in PostgreSQL
    assert len(calls) == 11


def test_gap_is_recorded_and_filled_in_data_gaps(engine, specs):
    clock = Clock(NOW + timedelta(minutes=15))  # 15:17
    missing = datetime(2026, 11, 10, 15, 5, tzinfo=UTC)
    service = IngestService(SyntheticProvider(specs, clock), specs, history_count=300)
    run_ingest_once(engine, service, clock)  # stores 15:05 and 15:10
    with engine.begin() as conn:
        conn.execute(
            text(
                "DELETE FROM candles WHERE instrument = 'EUR_USD' AND timeframe = '5m'"
                " AND open_time = :t"
            ),
            {"t": missing},
        )
    clock.now = NOW + timedelta(minutes=20)
    with engine.begin() as conn:
        report = service.ingest_instrument(SqlCandleStore(conn), "EUR_USD", clock.now)
    assert report.status == "ok"
    with engine.connect() as conn:
        gap = conn.execute(
            text("SELECT gap_from, gap_to, filled_at FROM data_gaps WHERE instrument = 'EUR_USD'")
        ).one()
    assert (gap.gap_from, gap.gap_to) == (missing, missing + timedelta(minutes=5))
    assert gap.filled_at == clock.now


def test_missing_series_status_row_is_recreated(engine, specs):
    """Review M4: the status write is an upsert, so a series missing from the seed shows up."""
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM series_status WHERE instrument = 'GBP_USD'"))
    clock = Clock(NOW + timedelta(minutes=25))
    service = IngestService(SyntheticProvider(specs, clock), specs, history_count=300)
    run_ingest_once(engine, service, clock)
    with engine.connect() as conn:
        n = conn.execute(
            text("SELECT count(*) FROM series_status WHERE instrument = 'GBP_USD'")
        ).scalar()
    assert n == 5
