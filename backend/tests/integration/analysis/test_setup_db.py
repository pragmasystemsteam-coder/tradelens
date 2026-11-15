"""Setups and revisions against a real PostgreSQL 16 (DD 8.2 task 2.3; FR-SMC-11).

Never point TEST_DATABASE_URL at real data: the schema is reset to base on every run.
"""

import os
from datetime import timedelta

import pytest

pytestmark = pytest.mark.integration

URL = os.environ.get("TEST_DATABASE_URL")
if not URL:
    pytest.skip("TEST_DATABASE_URL not set (needs PostgreSQL)", allow_module_level=True)

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from setup_batch import OB, SID, T, event, make_batch, weights  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from tradelens.cli.seed import seed  # noqa: E402
from tradelens.modules.analysis.output_store import SqlAnalysisStore  # noqa: E402
from tradelens.modules.analysis.public import load_scanner_rows  # noqa: E402
from tradelens.modules.analysis.setups import setup_from_engine_json  # noqa: E402

HOUR = timedelta(hours=1)


class BoomError(Exception):
    pass


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


def counts(conn):
    q = "SELECT (SELECT count(*) FROM setups), (SELECT count(*) FROM setup_revisions),"
    q += " (SELECT count(*) FROM market_events WHERE id = :b)"
    return tuple(conn.execute(text(q), {"b": "b" * 32}).one())


def save(engine, batch):
    with engine.begin() as conn:
        SqlAnalysisStore(conn).save_batch(batch)


def open_setups(engine):
    with engine.begin() as conn:
        docs = SqlAnalysisStore(conn).load_open_setups("EUR_USD", "a" * 64)
    return [setup_from_engine_json(d, weights()) for d in docs]


def test_setup_and_revision_one_transaction(engine):
    def failing_batch():
        with engine.begin() as conn:
            SqlAnalysisStore(conn).save_batch(make_batch())
            assert counts(conn) == (1, 1, 1)
            raise BoomError  # anything failing later in the batch rolls the setup back too

    with pytest.raises(BoomError):
        failing_batch()
    with engine.begin() as conn:
        assert counts(conn) == (0, 0, 0)
    save(engine, make_batch())
    with engine.begin() as conn:
        assert counts(conn) == (1, 1, 1)
        row = conn.execute(text("SELECT revision, status, q, c, combined, engine <> '{}'::jsonb"
                                " FROM setups WHERE id = :id"), {"id": SID}).one()  # fmt: skip
        rev = conn.execute(text("SELECT rev, reason, combined FROM setup_revisions"
                                " WHERE setup_id = :id"), {"id": SID}).one()  # fmt: skip
        rows = load_scanner_rows(conn, "a" * 64, 60)
    assert (row[0], row[1], row[5]) == (1, "confirmed", True)
    assert (rev[0], rev[1], rev[2]) == (1, "created", row[4])
    assert [r["id"] for r in rows] == [SID]
    assert rows[0]["zone"] == {"low": 108_000, "high": 108_050}


def test_reprocessing_is_noop(engine):
    save(engine, make_batch())
    save(engine, make_batch())  # the same close again (crash before the state was saved)
    with engine.begin() as conn:
        assert counts(conn) == (1, 1, 1)
    touch = T + HOUR
    second = make_batch(first=False, transitions=[(OB, "touched", touch)],
                        events=[event("c" * 32, "15m", touch + timedelta(minutes=30))],
                        last=T + 2 * HOUR, open_setups=open_setups(engine))  # fmt: skip
    save(engine, second)
    save(engine, second)
    save(engine, make_batch())  # an older batch never rewinds a newer revision
    with engine.begin() as conn:
        assert counts(conn)[:2] == (1, 2)
        revision, ltf = conn.execute(text("SELECT revision, ltf_confirmed_at IS NOT NULL"
                                          " FROM setups WHERE id = :id"),
                                     {"id": SID}).one()  # fmt: skip
        reasons = conn.execute(text("SELECT reason FROM setup_revisions WHERE setup_id = :id"
                                    " ORDER BY rev"), {"id": SID}).scalars().all()  # fmt: skip
    assert (revision, ltf) == (2, True)
    assert reasons == ["created", "ltf_confirmation"]
