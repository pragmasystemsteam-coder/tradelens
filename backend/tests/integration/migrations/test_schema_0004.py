"""Migration 0004 against PostgreSQL 16: Increment-3 tables and their guards (DD 2.2-2.7; task 3.1).

Never point TEST_DATABASE_URL at real data: the schema is reset to base on every run.
"""

import os

import pytest

pytestmark = pytest.mark.integration

URL = os.environ.get("TEST_DATABASE_URL")
if not URL:
    pytest.skip("TEST_DATABASE_URL not set (needs PostgreSQL)", allow_module_level=True)

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import create_engine, inspect, text  # noqa: E402
from sqlalchemy.exc import DBAPIError  # noqa: E402

from tradelens.cli.seed import seed  # noqa: E402
from tradelens.modules.accounts.public import create_account  # noqa: E402

I3_TABLES = {
    "trial_claims", "founder_claims", "payments", "billing_events", "refund_requests",
    "user_profiles", "profile_versions", "email_outbox", "alert_rules", "alert_deliveries",
    "notifications", "admin_audit_log", "app_errors", "monitor_alert_state",
}  # fmt: skip


def alembic_cfg(repo):
    cfg = Config(str(repo / "backend" / "alembic.ini"))
    cfg.set_main_option("script_location", str(repo / "backend" / "migrations"))
    return cfg


def migrate(repo, *steps):
    previous = os.environ.get("DATABASE_MIGRATION_URL")
    os.environ["DATABASE_MIGRATION_URL"] = URL
    try:
        for action, target in steps:
            getattr(command, action)(alembic_cfg(repo), target)
    finally:
        if previous is None:
            os.environ.pop("DATABASE_MIGRATION_URL", None)
        else:
            os.environ["DATABASE_MIGRATION_URL"] = previous


@pytest.fixture(scope="module")
def engine(request):
    repo = request.config.rootpath
    migrate(repo, ("downgrade", "base"), ("upgrade", "head"))
    eng = create_engine(URL)
    with eng.begin() as conn:
        seed(conn, repo / "config")
    yield eng
    eng.dispose()


def new_user(engine, email):
    with engine.begin() as conn:
        return create_account(conn, email, "customer", "not-a-real-hash")


def refused(engine, sql, params=None):
    with pytest.raises(DBAPIError) as err, engine.begin() as conn:
        conn.execute(text(sql), params or {})
    return str(err.value)


def test_increment3_tables_exist(engine):
    assert set(inspect(engine).get_table_names()) >= I3_TABLES


def test_audit_log_update_and_truncate_refused(engine):
    actor = new_user(engine, "audit0004@example.com")
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO admin_audit_log (actor_id, action, target_type, target_id)"
                          " VALUES (:a, 'plan.change', 'user', 'u1')"), {"a": actor})  # fmt: skip
    assert "append-only" in refused(engine, "UPDATE admin_audit_log SET reason = 'x'")
    assert "append-only" in refused(engine, "DELETE FROM admin_audit_log")
    assert "append-only" in refused(engine, "TRUNCATE admin_audit_log")
    with engine.begin() as conn:
        assert conn.execute(text("SELECT count(*) FROM admin_audit_log")).scalar() == 1


def test_profile_versions_update_refused(engine):
    owner = new_user(engine, "profile0004@example.com")
    with engine.begin() as conn:
        pid = conn.execute(text("INSERT INTO user_profiles (user_id, name) VALUES (:u, 'Mine')"
                                " RETURNING id"), {"u": owner}).scalar()  # fmt: skip
        conn.execute(text("INSERT INTO profile_versions (profile_id, version, settings, settings_hash)"
                          " VALUES (:p, 1, '{}', :h)"), {"p": pid, "h": "a" * 64})  # fmt: skip
    assert "append-only" in refused(engine, "UPDATE profile_versions SET version = 2")


def test_trial_claim_survives_user_delete(engine):
    uid = new_user(engine, "trial0004@example.com")
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO trial_claims (email_hash, user_id) VALUES (:h, :u)"),
                     {"h": "c" * 64, "u": uid})  # fmt: skip
        conn.execute(text("DELETE FROM users WHERE id = :u"), {"u": uid})
        left = conn.execute(text("SELECT user_id FROM trial_claims WHERE email_hash = :h"),
                            {"h": "c" * 64}).one()  # fmt: skip
    assert left[0] is None


def test_outbox_kind_and_status_checked(engine):
    assert "email_outbox_kind_check" in refused(
        engine, "INSERT INTO email_outbox (kind, to_email, subject) VALUES ('spam', 'a@b.c', 's')"
    )
    assert "email_outbox_status_check" in refused(
        engine, "INSERT INTO email_outbox (kind, to_email, subject, status)"
                " VALUES ('verify', 'a@b.c', 's', 'lost')")  # fmt: skip


def test_founder_claim_links_subscription(engine):
    fks = inspect(engine).get_foreign_keys("founder_claims")
    assert any(fk["referred_table"] == "subscriptions" for fk in fks)


def test_downgrade_to_0003_and_back(engine, request):
    repo = request.config.rootpath
    migrate(repo, ("downgrade", "0003"))
    assert not I3_TABLES & set(inspect(engine).get_table_names())
    migrate(repo, ("upgrade", "head"))
    assert set(inspect(engine).get_table_names()) >= I3_TABLES
