"""SQL for plans, prices, country currencies, founder slots and subscriptions (DD 2.2, 2.3)."""

from __future__ import annotations

import json
from collections.abc import Sequence
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
