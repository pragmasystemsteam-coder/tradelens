import io

import pytest
from alembic import command
from alembic.config import Config

I1_TABLES = [
    "trading_calendars",
    "instruments",
    "candles",
    "series_status",
    "data_gaps",
    "rule_versions",
    "presets",
    "series_state",
    "market_events",
    "liquidity_levels",
    "zones",
    "zone_transitions",
]
GUARD_TRIGGERS = [
    "market_events_append_only",
    "zone_transitions_append_only",
    "rule_versions_guard",
    "zones_guard",
    "presets_guard",
    "liquidity_levels_guard",
    "market_events_no_truncate",
    "zone_transitions_no_truncate",
    "rule_versions_no_truncate",
    "presets_no_truncate",
]


def offline_sql(repo, monkeypatch, *args) -> str:
    monkeypatch.delenv("DATABASE_MIGRATION_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    buffer = io.StringIO()
    cfg = Config(str(repo / "backend" / "alembic.ini"), output_buffer=buffer)
    cfg.set_main_option("script_location", str(repo / "backend" / "migrations"))
    cfg.set_main_option("sqlalchemy.url", "postgresql+psycopg://user:pass@localhost/tradelens")
    action, revision = args
    getattr(command, action)(cfg, revision, sql=True)
    return buffer.getvalue()


def test_migration_offline_sql_has_tables_and_triggers(repo, monkeypatch):
    sql = offline_sql(repo, monkeypatch, "upgrade", "head")
    for table in I1_TABLES:
        assert f"CREATE TABLE {table} (" in sql, table
    for trigger in GUARD_TRIGGERS:
        assert f"CREATE TRIGGER {trigger}" in sql, trigger
    assert "CREATE EXTENSION IF NOT EXISTS pgcrypto" in sql
    assert "CREATE EXTENSION IF NOT EXISTS citext" in sql
    assert "CREATE TABLE setups" not in sql  # Increment 2 (DD-8)
    assert "CREATE UNIQUE INDEX rule_versions_one_active" in sql


def test_migration_downgrade_drops_every_table(repo, monkeypatch):
    sql = offline_sql(repo, monkeypatch, "downgrade", "0001:base")
    for table in I1_TABLES:
        assert f"DROP TABLE IF EXISTS {table}" in sql, table
    assert "DROP FUNCTION IF EXISTS forbid_change" in sql


@pytest.mark.parametrize("table", ["candles", "market_events", "zones"])
def test_prices_are_bigint_not_numeric(repo, monkeypatch, table):
    sql = offline_sql(repo, monkeypatch, "upgrade", "head")
    block = sql.split(f"CREATE TABLE {table} (", 1)[1].split(");", 1)[0]
    assert (
        "numeric" not in block.lower()
        and "double" not in block.lower()
        and "real" not in block.lower()
    )


def table_block(sql: str, table: str) -> str:
    return sql.split(f"CREATE TABLE {table} (", 1)[1].split(");", 1)[0]


@pytest.mark.parametrize(
    "table", ["market_events", "zones", "liquidity_levels", "series_state", "presets"]
)
def test_engine_output_references_rule_versions(repo, monkeypatch, table):
    sql = offline_sql(repo, monkeypatch, "upgrade", "head")
    assert "REFERENCES rule_versions(version)" in table_block(sql, table)


@pytest.mark.parametrize(
    "table",
    [
        "candles",
        "series_status",
        "series_state",
        "market_events",
        "zones",
        "liquidity_levels",
        "data_gaps",
    ],
)
def test_every_timeframe_column_is_checked(repo, monkeypatch, table):
    sql = offline_sql(repo, monkeypatch, "upgrade", "head")
    assert "timeframe IN ('5m','15m','1h','4h','1d')" in table_block(sql, table)


def test_data_gaps_integrity(repo, monkeypatch):
    block = table_block(offline_sql(repo, monkeypatch, "upgrade", "head"), "data_gaps")
    assert "REFERENCES instruments(code)" in block
    assert "CHECK (gap_to > gap_from)" in block
