"""Schema guards and seed against a real, disposable PostgreSQL 16.

Set TEST_DATABASE_URL (owner role, e.g. postgresql+psycopg://tradelens_owner:pw@localhost:5432/tradelens_test).
The database is reset to base on every run, so never point this at real data.
"""

import os
from datetime import UTC, datetime, timedelta

import pytest

pytestmark = pytest.mark.integration

URL = os.environ.get("TEST_DATABASE_URL")
if not URL:
    pytest.skip(
        "TEST_DATABASE_URL not set (needs PostgreSQL; Docker not available)",
        allow_module_level=True,
    )

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.exc import DBAPIError  # noqa: E402

from tradelens.cli.seed import seed  # noqa: E402

T1 = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)
H = "a" * 64


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


def insert_event(conn, event_id="e" * 32):
    conn.execute(
        text(
            "INSERT INTO market_events (id, instrument, timeframe, settings_hash, rule_version, type, structure,"
            " direction, level, origin_time, confirm_time)"
            " VALUES (:id, 'EUR_USD', '5m', :h, 'r1.0', 'bos', 'internal', 'bull', 108535, :o, :c)"
        ),
        {"id": event_id, "h": H, "o": T1, "c": T1 + timedelta(minutes=5)},
    )


def insert_zone(conn, zone_id="z" * 32):
    conn.execute(
        text(
            "INSERT INTO zones (id, kind, instrument, timeframe, settings_hash, rule_version, direction, low, high,"
            " origin_time, confirm_time, state, state_time)"
            " VALUES (:id, 'ob', 'EUR_USD', '5m', :h, 'r1.0', 'bull', 108500, 108535, :o, :c, 'confirmed', :c)"
        ),
        {"id": zone_id, "h": H, "o": T1, "c": T1 + timedelta(minutes=5)},
    )


def raises_db_error(conn, sql, match, params=None):
    """Assert the statement fails for the expected reason (not a typo or an FK error)."""
    nested = conn.begin_nested()
    with pytest.raises(DBAPIError, match=match):
        conn.execute(text(sql), params or {})
    nested.rollback()


def test_seed_counts_in_db(engine):
    with engine.connect() as conn:
        count = lambda t: conn.execute(text(f"SELECT count(*) FROM {t}")).scalar_one()  # noqa: E731
        assert (count("instruments"), count("trading_calendars"), count("series_status")) == (
            11,
            2,
            55,
        )
        assert (count("rule_versions"), count("presets")) == (1, 4)
        assert (
            conn.execute(text("SELECT version FROM rule_versions WHERE is_active")).scalar_one()
            == "r1.0"
        )


def test_seed_idempotent(engine, request):
    with engine.begin() as conn:
        seed(conn, request.config.rootpath / "config")
        assert conn.execute(text("SELECT count(*) FROM instruments")).scalar_one() == 11
        assert (
            conn.execute(text("SELECT count(*) FROM rule_versions WHERE is_active")).scalar_one()
            == 1
        )


def test_market_events_append_only(engine):
    with engine.connect() as conn:
        tx = conn.begin()
        insert_event(conn)
        raises_db_error(conn, "UPDATE market_events SET level = 1", "append-only")
        raises_db_error(conn, "DELETE FROM market_events", "append-only")
        tx.rollback()


def test_zone_transitions_append_only(engine):
    with engine.connect() as conn:
        tx = conn.begin()
        insert_zone(conn)
        conn.execute(
            text(
                "INSERT INTO zone_transitions (zone_id, state, candle_time) VALUES (:z, 'confirmed', :t)"
            ),
            {"z": "z" * 32, "t": T1},
        )
        raises_db_error(conn, "UPDATE zone_transitions SET state = 'touched'", "append-only")
        raises_db_error(conn, "DELETE FROM zone_transitions", "append-only")
        tx.rollback()


def test_zones_boundary_immutable_state_updatable(engine):
    with engine.connect() as conn:
        tx = conn.begin()
        insert_zone(conn)
        conn.execute(text("UPDATE zones SET state = 'touched', retests = 1"))
        raises_db_error(conn, "UPDATE zones SET low = 1", "immutable")
        raises_db_error(conn, "UPDATE zones SET origin_time = now()", "immutable")
        raises_db_error(conn, "DELETE FROM zones", "not allowed")
        tx.rollback()


def test_rule_version_immutable(engine):
    with engine.connect() as conn:
        tx = conn.begin()
        conn.execute(text("UPDATE rule_versions SET is_active = false"))
        conn.execute(text("UPDATE rule_versions SET is_active = true"))
        raises_db_error(conn, "UPDATE rule_versions SET settings = '{}'::jsonb", "immutable")
        raises_db_error(conn, "UPDATE rule_versions SET weights = '{}'::jsonb", "immutable")
        raises_db_error(conn, "DELETE FROM rule_versions", "not allowed")
        tx.rollback()


def test_candles_reject_inconsistent_ohlc(engine):
    with engine.connect() as conn:
        tx = conn.begin()
        raises_db_error(
            conn,
            "INSERT INTO candles (instrument, timeframe, open_time, o, h, l, c, bid_o, bid_h, bid_l, bid_c,"
            " ask_o, ask_h, ask_l, ask_c) VALUES ('EUR_USD', '5m', now(), 100, 99, 98, 100,"
            " 100, 99, 98, 100, 100, 99, 98, 100)",
            "check constraint",
        )
        tx.rollback()


def test_presets_are_immutable(engine):
    with engine.connect() as conn:
        tx = conn.begin()
        raises_db_error(conn, "UPDATE presets SET name = 'x'", "append-only")
        raises_db_error(conn, "DELETE FROM presets", "append-only")
        tx.rollback()


def test_liquidity_level_identity_immutable_end_updatable(engine):
    with engine.connect() as conn:
        tx = conn.begin()
        conn.execute(
            text(
                "INSERT INTO liquidity_levels (id, instrument, timeframe, settings_hash, rule_version,"
                " kinds, side, price, origin_time, confirm_time)"
                " VALUES (:id, 'EUR_USD', '5m', :h, 'r1.0', ARRAY['pdh'], 'buy', 108600, :o, :o)"
            ),
            {"id": "l" * 32, "h": H, "o": T1},
        )
        conn.execute(text("UPDATE liquidity_levels SET end_time = now(), end_reason = 'swept'"))
        raises_db_error(conn, "UPDATE liquidity_levels SET price = 1", "immutable")
        raises_db_error(conn, "DELETE FROM liquidity_levels", "not allowed")
        tx.rollback()


def test_truncate_blocked_on_append_only_tables(engine):
    with engine.connect() as conn:
        for table in ("market_events", "zone_transitions", "rule_versions", "presets"):
            tx = conn.begin()
            raises_db_error(conn, f"TRUNCATE {table} CASCADE", "append-only")
            tx.rollback()


def test_seed_detects_rule_drift(engine, request, tmp_path):
    import json
    import shutil

    from tradelens.modules.analysis.public import RuleConfigError

    target = tmp_path / "config"
    shutil.copytree(request.config.rootpath / "config", target)
    path = target / "rules" / "r1.0.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["user"]["eq_tol_m"] = 200
    data["presets"][0]["user"]["eq_tol_m"] = 200
    path.write_text(json.dumps(data), encoding="utf-8")
    with engine.connect() as conn:
        tx = conn.begin()
        with pytest.raises(RuleConfigError, match=r"r1\.0"):
            seed(conn, target)
        tx.rollback()
