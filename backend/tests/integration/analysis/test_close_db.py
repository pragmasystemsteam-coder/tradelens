"""Close processing against a real PostgreSQL 16 (DD 8.1 task 1.9; FR-SMC-11, NFR-07).

Never point TEST_DATABASE_URL at real data: the schema is reset to base on every run.
"""

import json
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
from tradelens.modules.analysis.output_store import SqlAnalysisStore  # noqa: E402
from tradelens.modules.analysis.public import CloseProcessor, official_settings  # noqa: E402
from tradelens.modules.market_data.public import (  # noqa: E402
    IngestService,
    SqlCandleStore,
    load_instrument_specs,
)
from tradelens_engine.multi import run_multi  # noqa: E402
from tradelens_engine.types import Candle  # noqa: E402

T0 = datetime(2026, 11, 11, 21, 55, 2, tzinfo=UTC)
FIVE = timedelta(minutes=5)
TFS = ("5m", "15m", "1h", "4h", "1d")


@pytest.fixture(scope="module")
def repo(request):
    return request.config.rootpath


@pytest.fixture(scope="module")
def engine(repo):
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
def proc(repo):
    doc = json.loads((repo / "config" / "rules" / "r1.0.json").read_text(encoding="utf-8"))
    return CloseProcessor(official_settings(doc), "r1.0")


def ingest(engine, repo, code, now):
    specs = [s for s in load_instrument_specs(repo / "config") if s.code == code]
    service = IngestService(SyntheticProvider(specs, lambda: now), specs, history_count=300)
    with engine.begin() as conn:
        return service.ingest_instrument(SqlCandleStore(conn), code, now)


def process(engine, proc, code, now):
    # A fresh CloseProcessor per pass: only the database carries state between passes.
    fresh = CloseProcessor(proc.cfg, proc.rule_version)
    with engine.begin() as conn:
        return fresh.process(SqlCandleStore(conn), SqlAnalysisStore(conn), code, now)


def scalar(engine, sql, code):
    with engine.connect() as conn:
        return conn.execute(text(sql), {"i": code}).scalar()


def stored_event_ids(engine, code):
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id FROM market_events WHERE instrument = :i"), {"i": code})
        return sorted(r[0] for r in rows)


def batch_run_ids(engine, proc, code):
    """Event IDs of one uninterrupted engine run over every stored candle."""
    series = {}
    with engine.connect() as conn:
        store = SqlCandleStore(conn)
        for tf in TFS:
            series[tf] = [Candle(c.open_time, c.close_time, c.o, c.h, c.l, c.c, c.bid_c, c.ask_c)
                          for c in store.load(code, tf, None)]  # fmt: skip
    series = {tf: cs for tf, cs in series.items() if cs}
    res = run_multi(series, proc.cfg, instrument=code, rule_version="r1.0")
    return sorted(e.id for r in res.values() for e in r.events)


def test_events_and_state_one_transaction(engine, repo, proc, monkeypatch):
    code = "EUR_USD"
    assert ingest(engine, repo, code, T0).status == "ok"

    def crash(self, batch):
        raise RuntimeError("crash after events, before series_state")

    monkeypatch.setattr(SqlAnalysisStore, "_states", crash)
    with pytest.raises(RuntimeError):
        process(engine, proc, code, T0)
    # Nothing of the batch is stored: events and state commit together or not at all.
    for table in ("market_events", "zones", "liquidity_levels", "series_state"):
        assert scalar(engine, f"SELECT count(*) FROM {table} WHERE instrument = :i", code) == 0
    monkeypatch.undo()
    batch = process(engine, proc, code, T0)
    ids = {e.id for outs in batch.result.outputs.values() for o in outs for e in o.events}
    assert stored_event_ids(engine, code) == sorted(ids)
    assert scalar(engine, "SELECT count(*) FROM series_state WHERE instrument = :i", code) == 5
    assert scalar(engine, "SELECT count(*) FROM zones WHERE instrument = :i", code) > 0


def test_restart_continues_same_events(engine, repo, proc):
    code = "GBP_USD"
    now = T0
    for _ in range(4):
        assert ingest(engine, repo, code, now).status == "ok"
        process(engine, proc, code, now)
        now += FIVE
    assert stored_event_ids(engine, code) == batch_run_ids(engine, proc, code)
    as_of = scalar(engine, "SELECT max(as_of) FROM series_state WHERE instrument = :i", code)
    assert as_of == datetime(2026, 11, 11, 22, 10, tzinfo=UTC)


def test_reprocessing_is_harmless(engine, proc):
    # A state rebuilt from candles writes the same deterministic IDs; inserts do nothing.
    code = "GBP_USD"
    before = stored_event_ids(engine, code)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM series_state WHERE instrument = :i"), {"i": code})
    assert process(engine, proc, code, T0 + 3 * FIVE) is not None
    assert stored_event_ids(engine, code) == before


def test_zone_lifecycle_columns_follow_transitions(engine):
    with engine.connect() as conn:
        bad = conn.execute(text(
            "SELECT count(*) FROM zones z WHERE z.state <> (SELECT t.state FROM zone_transitions t"
            " WHERE t.zone_id = z.id AND t.state <> 'detected'"
            " ORDER BY t.candle_time DESC, CASE t.state WHEN 'confirmed' THEN 0 WHEN 'touched' THEN 1"
            " WHEN 'mitigated_50' THEN 2 WHEN 'filled' THEN 3 ELSE 4 END DESC LIMIT 1)"
        )).scalar()  # fmt: skip
    assert bad == 0
