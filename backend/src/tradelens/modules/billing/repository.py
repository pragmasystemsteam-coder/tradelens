"""SQL for plans, prices, country currencies, founder slots and subscriptions (DD 2.2, 2.3)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, text

CLEAR_DEFAULT = text("UPDATE plans SET is_default = false WHERE is_default AND code <> :code")
CLEAR_TRIAL = text(
    "UPDATE plans SET trial_days = 0 WHERE trial_days > 0"
    " AND (CAST(:code AS text) IS NULL OR code <> :code)"
)
UPSERT_PLAN = text(
    "INSERT INTO plans (code, name, is_paid, is_default, tier_rank, trial_days, limits,"
    " sort_order, is_public, active) VALUES (:code, :name, :is_paid, :is_default, :tier_rank,"
    " :trial_days, CAST(:limits AS jsonb), :sort_order, :is_public, :active)"
    " ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, is_paid = EXCLUDED.is_paid,"
    " is_default = EXCLUDED.is_default, tier_rank = EXCLUDED.tier_rank,"
    " trial_days = EXCLUDED.trial_days, limits = EXCLUDED.limits,"
    " sort_order = EXCLUDED.sort_order, is_public = EXCLUDED.is_public, active = EXCLUDED.active"
)
SET_RENEWS_INTO = text("UPDATE plans SET renews_into = :renews_into WHERE code = :code")
UPSERT_PRICE = text(
    "INSERT INTO plan_prices (plan_code, currency, amount_minor, interval, razorpay_plan_id)"
    " VALUES (:plan_code, :currency, :amount_minor, :interval, :razorpay_plan_id)"
    " ON CONFLICT (plan_code, currency) DO UPDATE SET amount_minor = EXCLUDED.amount_minor,"
    " interval = EXCLUDED.interval, razorpay_plan_id = EXCLUDED.razorpay_plan_id"
)
UPSERT_COUNTRY = text(
    "INSERT INTO country_currency (country, currency) VALUES (:country, :currency)"
    " ON CONFLICT (country) DO UPDATE SET currency = EXCLUDED.currency"
)
UPSERT_FOUNDER = text(
    "INSERT INTO founder_slots (plan_code, cap) VALUES (:plan_code, :cap)"
    " ON CONFLICT (plan_code) DO UPDATE SET cap = EXCLUDED.cap"
)
SELECT_DEFAULT = text("SELECT is_default FROM plans WHERE code = :code")
INSERT_MANUAL = text(
    "INSERT INTO subscriptions (user_id, plan_code, source, status)"
    " VALUES (:user_id, :plan_code, 'manual', 'active') RETURNING id"
)


def clear_flags(conn: Connection, default_code: str, trial_code: str | None) -> None:
    """Drop the default and trial flags from every plan that is not keeping them."""
    conn.execute(CLEAR_DEFAULT, {"code": default_code})
    conn.execute(CLEAR_TRIAL, {"code": trial_code})


def upsert_plans(conn: Connection, rows: Sequence[dict[str, Any]]) -> None:
    """Insert or update plans; ``renews_into`` is set after all codes exist (self FK)."""
    if not rows:
        return
    conn.execute(UPSERT_PLAN, [{**r, "limits": json.dumps(r["limits"])} for r in rows])
    renews = [{"code": r["code"], "renews_into": r["renews_into"]} for r in rows]
    conn.execute(SET_RENEWS_INTO, renews)


def upsert_prices(conn: Connection, rows: Sequence[dict[str, Any]]) -> None:
    """Insert or update plan prices."""
    if rows:
        conn.execute(UPSERT_PRICE, list(rows))


def upsert_country_currency(conn: Connection, pairs: Sequence[tuple[str, str]]) -> None:
    """Insert or update the billing country to currency map."""
    if pairs:
        conn.execute(UPSERT_COUNTRY, [{"country": c, "currency": cur} for c, cur in pairs])


def upsert_founder_slots(conn: Connection, rows: Sequence[dict[str, Any]]) -> None:
    """Insert or update founder caps (``used`` is never touched)."""
    if rows:
        conn.execute(UPSERT_FOUNDER, list(rows))


def fetch_plan_default(conn: Connection, code: str) -> bool | None:
    """``is_default`` of a plan, or None when the plan does not exist."""
    value = conn.execute(SELECT_DEFAULT, {"code": code}).scalar()
    return None if value is None else bool(value)


def insert_manual_subscription(conn: Connection, user_id: str, plan_code: str) -> str:
    """Insert an active ``manual`` subscription and return its ID."""
    return str(conn.execute(INSERT_MANUAL, {"user_id": user_id, "plan_code": plan_code}).scalar())


SELECT_PLANS = text(
    "SELECT code, name, is_paid, is_default, tier_rank, trial_days, limits, is_public, active"
    " FROM plans ORDER BY sort_order, code"
)
# The newest subscription that may still grant a plan; dates are checked by the service.
SELECT_LIVE_SUBSCRIPTION = text(
    "SELECT plan_code, status, trial_ends_at, current_period_end, grace_until,"
    " cancel_at_period_end, pending_plan_code FROM subscriptions WHERE user_id = :user_id"
    " AND status IN ('trialing', 'active', 'grace', 'cancelled')"
    " ORDER BY created_at DESC, id LIMIT 1"
)


def fetch_plans(conn: Connection) -> list[dict[str, Any]]:
    """Every plan row (active and inactive)."""
    return [dict(r) for r in conn.execute(SELECT_PLANS).mappings()]


def fetch_live_subscription(conn: Connection, user_id: str) -> dict[str, Any] | None:
    """The newest trialing, active, grace or cancelled subscription of a user, if any."""
    row = conn.execute(SELECT_LIVE_SUBSCRIPTION, {"user_id": user_id}).mappings().first()
    return None if row is None else dict(row)


# ---------------------------------------------------------------- trial and deletion (task 3.2)
SELECT_TRIAL_PLAN = text(
    "SELECT code, trial_days FROM plans WHERE trial_days > 0 AND active LIMIT 1"
)
SELECT_OPEN_SUBSCRIPTION = text(
    "SELECT id FROM subscriptions WHERE user_id = :user_id"
    " AND status IN ('created', 'trialing', 'active', 'grace') LIMIT 1"
)
CLAIM_TRIAL = text(
    "INSERT INTO trial_claims (email_hash, user_id, claimed_at) VALUES (:hash, :user_id, :now)"
    " ON CONFLICT (email_hash) DO NOTHING RETURNING email_hash"
)
INSERT_TRIAL = text(
    "INSERT INTO subscriptions (user_id, plan_code, source, status, trial_ends_at, created_at,"
    " updated_at) VALUES (:user_id, :plan_code, 'trial', 'trialing', :ends, :now, :now)"
)
END_OPEN = text(
    "UPDATE subscriptions SET"
    " status = CASE WHEN status IN ('active', 'grace', 'cancelled') THEN 'cancelled'"
    "   ELSE 'expired' END,"
    " current_period_end = CASE WHEN status IN ('active', 'grace', 'cancelled')"
    "   THEN LEAST(COALESCE(current_period_end, :now), :now) ELSE current_period_end END,"
    " grace_until = LEAST(grace_until, :now), cancel_at_period_end = true,"
    " ended_at = COALESCE(ended_at, :now), updated_at = :now"
    " WHERE user_id = :user_id"
    " AND status IN ('created', 'trialing', 'active', 'grace', 'cancelled')"
    " AND ended_at IS NULL"
)


def fetch_trial_plan(conn: Connection) -> dict[str, Any] | None:
    """The active plan a trial grants (``trial_days > 0``), if any."""
    row = conn.execute(SELECT_TRIAL_PLAN).mappings().first()
    return None if row is None else dict(row)


def fetch_open_subscription(conn: Connection, user_id: str) -> str | None:
    """ID of a created, trialing, active or grace subscription."""
    found = conn.execute(SELECT_OPEN_SUBSCRIPTION, {"user_id": user_id}).scalar()
    return None if found is None else str(found)


def claim_trial(conn: Connection, hashed_email: str, user_id: str, now: datetime) -> bool:
    """Insert the claim; False when this e-mail already had a trial."""
    params = {"hash": hashed_email, "user_id": user_id, "now": now}
    return conn.execute(CLAIM_TRIAL, params).first() is not None


def insert_trial_subscription(
    conn: Connection, user_id: str, plan_code: str, now: datetime, ends: datetime
) -> None:
    """A ``trialing`` subscription (source ``trial``, no card)."""
    conn.execute(INSERT_TRIAL, {"user_id": user_id, "plan_code": plan_code, "now": now,
                                "ends": ends})  # fmt: skip


def end_open_subscriptions(conn: Connection, user_id: str, now: datetime) -> None:
    """Paid rows become cancelled (period ends now); trials and checkouts become expired."""
    conn.execute(END_OPEN, {"user_id": user_id, "now": now})
