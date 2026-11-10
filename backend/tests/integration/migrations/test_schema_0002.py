"""Migration 0002 against a real PostgreSQL 16: accounts, plans, subscriptions, setups (task 2.1).

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
from sqlalchemy.exc import DBAPIError  # noqa: E402

from tradelens.cli.create_user import create_user  # noqa: E402
from tradelens.cli.seed import seed  # noqa: E402
from tradelens.modules.billing.public import build_plan_rows, save_plan_rows  # noqa: E402

T1 = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)
H = "a" * 64


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
        seed(conn, repo / "config")  # reference data, rule r1.0 and the plans
        conn.execute(text(
            "INSERT INTO market_events (id, instrument, timeframe, settings_hash, rule_version, type,"
            " structure, direction, level, origin_time, confirm_time) VALUES"
            " (:id, 'EUR_USD', '1h', :h, 'r1.0', 'bos', 'internal', 'bull', 108535, :o, :c)"
        ), {"id": "e" * 32, "h": H, "o": T1, "c": T1 + timedelta(hours=1)})  # fmt: skip
        conn.execute(text(
            "INSERT INTO zones (id, kind, instrument, timeframe, settings_hash, rule_version, direction,"
            " low, high, origin_time, confirm_time, state, state_time) VALUES (:id, 'ob', 'EUR_USD',"
            " '1h', :h, 'r1.0', 'bull', 108500, 108535, :o, :c, 'confirmed', :c)"
        ), {"id": "z" * 32, "h": H, "o": T1, "c": T1 + timedelta(hours=1)})  # fmt: skip
    yield eng
    eng.dispose()


def fails(conn, sql, match, params=None):
    nested = conn.begin_nested()
    with pytest.raises(DBAPIError, match=match):
        conn.execute(text(sql), params or {})
    nested.rollback()


SETUP_SQL = (
    "INSERT INTO setups (id, instrument, asset_class, timeframe, profile, settings_hash, rule_version,"
    " scoring_version, direction, break_event_id, break_type, patterns, sessions, spread, q, c, combined,"
    " counter_trend, factors, explanation, ob_zone_id, invalidation, status, status_time, origin_time,"
    " confirm_time) VALUES (:id, 'EUR_USD', 'forex', :tf, :profile, :h, 'r1.0', 's1.0', 'bull', :e, 'bos',"
    " ARRAY['bos','displacement','ob'], ARRAY['london'], 0, 70, 60, 66, false, '[]', 'x', :z, 108500,"
    " 'confirmed', :c, :o, :c)"
)


def setup_params(sid, tf="1h", profile="intraday"):
    return {"id": sid, "tf": tf, "profile": profile, "h": H, "e": "e" * 32, "z": "z" * 32,
            "o": T1, "c": T1 + timedelta(hours=1)}  # fmt: skip


def test_plans_seed(engine):
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM plans")).scalar() == 4
        assert conn.execute(text("SELECT count(*) FROM plan_prices")).scalar() == 6
        assert conn.execute(text("SELECT code FROM plans WHERE is_default")).scalars().all() == [
            "free"
        ]
        trial = conn.execute(text("SELECT code FROM plans WHERE trial_days > 0")).scalars().all()
        assert trial == ["pro_monthly"]
        assert tuple(conn.execute(text("SELECT cap, used FROM founder_slots")).one()) == (100, 0)
        assert (
            conn.execute(text("SELECT currency FROM country_currency WHERE country = '*'")).scalar()
            == "USD"
        )
        limits = conn.execute(text("SELECT limits FROM plans WHERE code = 'pro_annual'")).scalar()
        assert limits["max_watchlists"] == 3
        assert limits["mtf_detail"] == "full"


def test_load_plans_is_idempotent_and_updates_limits(engine, repo):
    doc = json.loads((repo / "config" / "plans.json").read_text(encoding="utf-8"))
    doc["plans"][0]["limits"]["max_alert_rules"] = 4
    with engine.begin() as conn:
        save_plan_rows(conn, build_plan_rows(doc))
        save_plan_rows(conn, build_plan_rows(doc))
        assert conn.execute(text("SELECT count(*) FROM plans")).scalar() == 4
        limit = conn.execute(
            text("SELECT limits->>'max_alert_rules' FROM plans WHERE code = 'free'")
        ).scalar()
        assert limit == "4"
        conn.rollback()


def test_two_trial_plans_fail_load(engine):
    with engine.begin() as conn:
        fails(conn, "UPDATE plans SET trial_days = 15 WHERE code = 'pro_annual'", "plans_one_trial")
        fails(conn, "UPDATE plans SET is_default = true WHERE code = 'pro_monthly'", "plans_")


def test_setup_profile_timeframe_check(engine):
    with engine.begin() as conn:
        fails(conn, SETUP_SQL, "check", setup_params("s" * 32, tf="1h", profile="scalping"))
        fails(conn, SETUP_SQL, "check", setup_params("s" * 32, tf="5m", profile="scalping"))
        conn.execute(text(SETUP_SQL), setup_params("s" * 32))  # 1h + intraday is fine
        conn.rollback()


def test_setup_identity_immutable(engine):
    with engine.begin() as conn:
        conn.execute(text(SETUP_SQL), setup_params("t" * 32))
        conn.execute(text("UPDATE setups SET q = 80, combined = 72, status = 'invalidated',"
                          " revision = 2 WHERE id = :id"), {"id": "t" * 32})  # fmt: skip
        fails(
            conn,
            "UPDATE setups SET direction = 'bear' WHERE id = :id",
            "immutable",
            {"id": "t" * 32},
        )
        fails(
            conn, "UPDATE setups SET invalidation = 1 WHERE id = :id", "immutable", {"id": "t" * 32}
        )
        fails(conn, "DELETE FROM setups WHERE id = :id", "not allowed", {"id": "t" * 32})
        conn.rollback()


def test_setup_revisions_append_only(engine):
    with engine.begin() as conn:
        conn.execute(text(SETUP_SQL), setup_params("u" * 32))
        conn.execute(text(
            "INSERT INTO setup_revisions (setup_id, rev, q, c, combined, status, factors, reason,"
            " effective_time) VALUES (:id, 1, 70, 60, 66, 'confirmed', '[]', 'created', :t)"
        ), {"id": "u" * 32, "t": T1})  # fmt: skip
        fails(conn, "UPDATE setup_revisions SET q = 1", "append-only")
        fails(conn, "DELETE FROM setup_revisions", "append-only")
        fails(conn, "TRUNCATE setup_revisions", "append-only")
        fails(conn, "INSERT INTO setup_revisions (setup_id, rev, q, c, combined, status, factors, reason,"
                    " effective_time) VALUES (:id, 2, 70, 60, 66, 'confirmed', '[]', 'bored', :t)",
              "check", {"id": "u" * 32, "t": T1})  # fmt: skip
        conn.rollback()


def test_one_created_subscription_per_user(engine):
    with engine.begin() as conn:
        uid = conn.execute(text("INSERT INTO users (email, password_hash) VALUES ('sub@example.com', 'x')"
                                " RETURNING id")).scalar()  # fmt: skip
        sql = ("INSERT INTO subscriptions (user_id, plan_code, source, currency, status)"
               " VALUES (:u, 'pro_monthly', 'razorpay', 'INR', :s)")  # fmt: skip
        conn.execute(text(sql), {"u": uid, "s": "created"})
        fails(conn, sql, "subscriptions_one_created", {"u": uid, "s": "created"})
        conn.execute(text(sql), {"u": uid, "s": "active"})
        fails(conn, sql, "subscriptions_one_live", {"u": uid, "s": "active"})
        fails(conn, "INSERT INTO subscriptions (user_id, plan_code, source, status)"
                    " VALUES (:u, 'pro_monthly', 'trial', 'trialing')", "check", {"u": uid})  # fmt: skip
        conn.rollback()


def test_users_email_unique_while_live_and_case_insensitive(engine):
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO users (email, password_hash) VALUES ('Case@Example.com', 'x')")
        )
        fails(
            conn,
            "INSERT INTO users (email, password_hash) VALUES ('case@example.com', 'x')",
            "users_email_live",
        )
        conn.execute(text("UPDATE users SET deleted_at = now() WHERE email = 'case@example.com'"))
        conn.execute(
            text("INSERT INTO users (email, password_hash) VALUES ('case@example.com', 'x')")
        )
        conn.rollback()


def test_rule_versions_created_by_references_users(engine):
    with engine.begin() as conn:
        fails(conn, "INSERT INTO rule_versions (version, settings, settings_hash, weights, created_by)"
                    " VALUES ('r9', '{}', :h, '{}', gen_random_uuid())", "foreign key", {"h": H})  # fmt: skip
        conn.rollback()


def test_watchlist_items_cascade_with_watchlist(engine):
    with engine.begin() as conn:
        uid = conn.execute(text("INSERT INTO users (email, password_hash) VALUES ('w@example.com', 'x')"
                                " RETURNING id")).scalar()  # fmt: skip
        wid = conn.execute(text("INSERT INTO watchlists (user_id, name) VALUES (:u, 'Main') RETURNING id"),
                           {"u": uid}).scalar()  # fmt: skip
        conn.execute(text("INSERT INTO watchlist_items (watchlist_id, instrument) VALUES (:w, 'EUR_USD')"),
                     {"w": wid})  # fmt: skip
        fails(
            conn, "INSERT INTO watchlists (user_id, name) VALUES (:u, 'Main')", "unique", {"u": uid}
        )
        conn.execute(text("DELETE FROM watchlists WHERE id = :w"), {"w": wid})
        left = conn.execute(
            text("SELECT count(*) FROM watchlist_items WHERE watchlist_id = :w"), {"w": wid}
        )
        assert left.scalar() == 0
        conn.rollback()


def test_liquidity_level_kinds_change_only_while_active(engine):
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO liquidity_levels (id, instrument, timeframe, settings_hash, rule_version, kinds,"
            " side, price, origin_time, confirm_time) VALUES ('l' || repeat('0', 31), 'EUR_USD', '1h', :h,"
            " 'r1.0', ARRAY['swing_high'], 'buy', 108600, :t, :t)"
        ), {"h": H, "t": T1})  # fmt: skip
        conn.execute(text("UPDATE liquidity_levels SET kinds = ARRAY['swing_high','pdh']"))  # joins
        conn.execute(
            text("UPDATE liquidity_levels SET kinds = ARRAY['pdh']")
        )  # superseded kind leaves
        fails(conn, "UPDATE liquidity_levels SET kinds = '{}'", "check")
        fails(conn, "UPDATE liquidity_levels SET price = 1", "immutable")
        conn.execute(
            text("UPDATE liquidity_levels SET end_time = :t, end_reason = 'swept'"), {"t": T1}
        )
        fails(conn, "UPDATE liquidity_levels SET kinds = ARRAY['pdh','pwh']", "immutable")
        conn.rollback()


def test_create_user_inserts_manual_subscription(engine):
    with engine.begin() as conn:
        uid = create_user(conn, "pro@example.com", "customer", "pro_monthly", "hash")
        row = conn.execute(text("SELECT plan_code, source, status, currency FROM subscriptions"
                                " WHERE user_id = :u"), {"u": uid}).one()  # fmt: skip
        assert tuple(row) == ("pro_monthly", "manual", "active", None)
        free = create_user(conn, "free@example.com", "support", "free", "hash")
        count = conn.execute(
            text("SELECT count(*) FROM subscriptions WHERE user_id = :u"), {"u": free}
        )
        assert count.scalar() == 0  # the default plan needs no subscription row
        with pytest.raises(ValueError, match="unknown plan"):
            create_user(conn, "x@example.com", "customer", "gold", "hash")
        conn.rollback()
