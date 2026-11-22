"""Plans, prices and limits from config/plans.json (DD 2.2, 6.2; CR-003, FR-SUB-01, DD-2).

Plans are data: any number of plans, exactly one default plan (the limits of a user without a
live subscription) and at most one trial plan (found by ``trial_days > 0``, never by code).
Limit keys are a closed list; an unknown key fails the load, so a typo cannot silently remove
a limit. A missing key is allowed and means the documented default (applied by entitlements,
task 2.4). ``null`` for a count means unlimited.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from redis.exceptions import RedisError
from sqlalchemy import Connection

from tradelens.core.limits import Limits, best_of, with_defaults
from tradelens.modules.billing import repository

Row = dict[str, Any]
ASSET_CLASSES = ("forex", "metal", "energy")
MTF_DETAIL = ("strip", "full")
INTERVALS = ("month", "year")
PLAN_KEYS = frozenset({"code", "name", "is_paid", "is_default", "tier_rank", "renews_into",
                       "trial_days", "limits", "sort_order", "is_public", "active", "prices",
                       "founder_cap"})  # fmt: skip
SMALLINT_MAX = 32767
INT_MAX = 2**31 - 1
CURRENCY_LEN = 3
MODES = ("test", "live")


class PlanConfigError(ValueError):
    """A plans file that must not be loaded."""


def _count(name: str, value: object) -> None:
    if value is not None and (type(value) is not int or value < 0):
        raise PlanConfigError(f"limit {name} must be a non-negative integer or null, got {value!r}")


def _flag(name: str, value: object) -> None:
    if type(value) is not bool:
        raise PlanConfigError(f"limit {name} must be true or false, got {value!r}")


def _asset_classes(name: str, value: object) -> None:
    if not isinstance(value, list) or not value or not set(value) <= set(ASSET_CLASSES):
        raise PlanConfigError(f"limit {name} must be a non-empty list of {ASSET_CLASSES}")


def _mtf(name: str, value: object) -> None:
    if value not in MTF_DETAIL:
        raise PlanConfigError(f"limit {name} must be one of {MTF_DETAIL}, got {value!r}")


# DD 6.2: the closed list of limit keys and their types.
LIMIT_KEYS: dict[str, Callable[[str, object], None]] = {
    "asset_classes": _asset_classes,
    "mtf_detail": _mtf,
    "chart_history_candles": _count,
    "max_watchlists": _count,
    "max_watchlist_items": _count,
    "max_alert_rules": _count,
    "custom_settings": _flag,
    "max_profiles": _count,
    "custom_watchlist_pairs_max": _count,
}


@dataclass(frozen=True, slots=True)
class PlanRows:
    """Rows for plans, plan_prices, country_currency and founder_slots."""

    plans: tuple[Row, ...]
    prices: tuple[Row, ...]
    country_currency: tuple[tuple[str, str], ...]
    founder_slots: tuple[Row, ...]


def _limits(where: str, limits: object) -> dict[str, Any]:
    if not isinstance(limits, Mapping):
        raise PlanConfigError(f"{where}: limits must be an object or '@<limit set>'")
    unknown = sorted(set(limits) - set(LIMIT_KEYS))
    if unknown:
        raise PlanConfigError(f"{where}: unknown limit key(s) {unknown}")
    for key, value in limits.items():
        LIMIT_KEYS[key](key, value)
    return dict(limits)


def _int(where: str, name: str, value: object, low: int = 0, high: int = SMALLINT_MAX) -> int:
    if type(value) is not int or not low <= value <= high:
        raise PlanConfigError(f"{where}: {name} must be an integer in {low}..{high}")
    return value


def _bool(where: str, name: str, value: object) -> bool:
    if type(value) is not bool:
        raise PlanConfigError(f"{where}: {name} must be true or false")
    return value


def _prices(where: str, plan: Mapping[str, Any], ids: Mapping[str, str]) -> list[Row]:
    rows = []
    for currency, price in plan.get("prices", {}).items():
        if len(currency) != CURRENCY_LEN or not currency.isupper():
            raise PlanConfigError(f"{where}: bad currency {currency!r}")
        if price.get("interval") not in INTERVALS:
            raise PlanConfigError(f"{where} {currency}: interval must be one of {INTERVALS}")
        amount = _int(f"{where} {currency}", "amount_minor", price.get("amount_minor"), 1, INT_MAX)
        rows.append({
            "plan_code": plan["code"], "currency": currency, "amount_minor": amount,
            "interval": price["interval"],
            "razorpay_plan_id": ids.get(f"{plan['code']}:{currency}"),
        })  # fmt: skip
    return rows


def _plan(item: Mapping[str, Any], limit_sets: Mapping[str, Any], order: int) -> Row:
    code = item.get("code")
    if not isinstance(code, str) or not code:
        raise PlanConfigError("every plan needs a code")
    where = f"plan {code}"
    unknown = sorted(set(item) - PLAN_KEYS)
    if unknown:
        raise PlanConfigError(f"{where}: unknown key(s) {unknown}")
    limits = item.get("limits")
    if isinstance(limits, str):
        name = limits.removeprefix("@")
        if not limits.startswith("@") or name not in limit_sets:
            raise PlanConfigError(f"{where}: unknown limit set {limits!r}")
        limits = limit_sets[name]
    is_paid = _bool(where, "is_paid", item.get("is_paid"))
    if not is_paid and item.get("prices"):
        raise PlanConfigError(f"{where}: a free plan has no prices")
    return {
        "code": code, "name": str(item.get("name", code)), "is_paid": is_paid,
        "is_default": _bool(where, "is_default", item.get("is_default", False)),
        "tier_rank": _int(where, "tier_rank", item.get("tier_rank", 0)),
        "renews_into": item.get("renews_into"),
        "trial_days": _int(where, "trial_days", item.get("trial_days", 0)),
        "limits": _limits(where, limits),
        "sort_order": _int(where, "sort_order", item.get("sort_order", order)),
        "is_public": _bool(where, "is_public", item.get("is_public", True)),
        "active": _bool(where, "active", item.get("active", True)),
    }  # fmt: skip


def _check_plans(plans: Sequence[Row]) -> None:
    codes = [p["code"] for p in plans]
    dupes = sorted({c for c in codes if codes.count(c) > 1})
    if dupes:
        raise PlanConfigError(f"duplicate plan code(s) {dupes}")
    defaults = [p["code"] for p in plans if p["is_default"]]
    if len(defaults) != 1:
        raise PlanConfigError(f"exactly one default plan is required, found {defaults}")
    if any(p["is_paid"] for p in plans if p["is_default"]):
        raise PlanConfigError("the default plan must be free")
    trials = [p["code"] for p in plans if p["trial_days"] > 0]
    if len(trials) > 1:
        raise PlanConfigError(f"at most one trial plan is allowed, found {trials}")
    for p in plans:
        if p["renews_into"] is not None and p["renews_into"] not in codes:
            raise PlanConfigError(f"plan {p['code']}: renews_into {p['renews_into']!r} is unknown")


def build_plan_rows(doc: Mapping[str, Any], *, mode: str = "test") -> PlanRows:
    """Validate config/plans.json and turn it into table rows.

    Args:
        doc: The parsed plans file.
        mode: Razorpay mode (``RAZORPAY_MODE``) whose plan IDs are used.

    Returns:
        The rows to upsert.

    Raises:
        PlanConfigError: On unknown keys or limit keys, wrong types, not exactly one default
            plan, two trial plans, bad prices or an unknown ``renews_into``.
    """
    if mode not in MODES:
        raise PlanConfigError(f"mode must be one of {MODES}")
    limit_sets = doc.get("limit_sets", {})
    for name, limits in limit_sets.items():
        _limits(f"limit set {name}", limits)
    plans = [_plan(item, limit_sets, i) for i, item in enumerate(doc.get("plans", []))]
    _check_plans(plans)
    ids = doc.get("razorpay_plan_ids", {}).get(mode, {})
    by_code = {item["code"]: item for item in doc["plans"]}
    prices = [row for p in plans for row in _prices(f"plan {p['code']}", by_code[p["code"]], ids)]
    for p in plans:
        if p["is_paid"] and not any(r["plan_code"] == p["code"] for r in prices):
            raise PlanConfigError(f"plan {p['code']}: a paid plan needs at least one price")
    countries = doc.get("country_currency", {})
    if "*" not in countries:
        raise PlanConfigError("country_currency needs the '*' default row")
    founders = [
        {"plan_code": item["code"],
         "cap": _int(f"plan {item['code']}", "founder_cap", item["founder_cap"], 0, INT_MAX)}
        for item in doc["plans"] if "founder_cap" in item
    ]  # fmt: skip
    return PlanRows(tuple(plans), tuple(prices), tuple(countries.items()), tuple(founders))


def save_plan_rows(conn: Connection, rows: PlanRows) -> None:
    """Upsert plans, prices, country currencies and founder caps (``make load-plans``).

    Changing plans.json changes limits without code (FR-SUB-01). The default and trial flags
    move in two steps so the one-default and one-trial unique indexes never see two rows.

    Args:
        conn: Connection inside the caller's transaction (owner role).
        rows: Rows from :func:`build_plan_rows`.
    """
    default = next(p["code"] for p in rows.plans if p["is_default"])
    trial = next((p["code"] for p in rows.plans if p["trial_days"] > 0), None)
    repository.clear_flags(conn, default, trial)
    repository.upsert_plans(conn, rows.plans)
    repository.upsert_prices(conn, rows.prices)
    repository.upsert_country_currency(conn, rows.country_currency)
    repository.upsert_founder_slots(conn, rows.founder_slots)


def plan_is_default(conn: Connection, code: str) -> bool:
    """Whether ``code`` is the default plan.

    Raises:
        ValueError: If no plan has this code.
    """
    found = repository.fetch_plan_default(conn, code)
    if found is None:
        raise ValueError(f"unknown plan {code!r}")
    return found


def create_manual_subscription(conn: Connection, user_id: str, plan_code: str) -> str:
    """Give a user a plan without payment (demo and support accounts; source ``manual``).

    Returns:
        The subscription ID.
    """
    return repository.insert_manual_subscription(conn, user_id, plan_code)


# ---------------------------------------------------------------- entitlements (DD 4.3, task 2.4)
ENT_TTL_SECONDS = 60


def _iso(t: datetime | None) -> str | None:
    return None if t is None else t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _grants(sub: Mapping[str, Any] | None, now: datetime) -> str | None:
    """``paid``, ``trial`` or None: what a subscription row grants at ``now`` (DD 4.3)."""
    if sub is None:
        return None
    status = sub["status"]
    if status == "active":
        return "paid"
    if status == "grace" and sub.get("grace_until") is not None and now < sub["grace_until"]:
        return "paid"
    end = sub.get("current_period_end")
    if status == "cancelled" and end is not None and now < end:
        return "paid"
    trial_end = sub.get("trial_ends_at")
    if status == "trialing" and trial_end is not None and now < trial_end:
        return "trial"
    return None


def resolve_limits(
    plans: Sequence[Mapping[str, Any]], sub: Mapping[str, Any] | None, now: datetime
) -> Limits:
    """A user's effective limits from plan rows and their newest subscription (DD 4.3).

    A live paid subscription gives its plan's limits; else a running trial gives the trial
    plan's (the plan with ``trial_days > 0``); else the default plan. Plan codes are only
    looked up, never compared with literals (FR-SUB-01).

    Args:
        plans: Plan rows (``code``, ``name``, ``is_default``, ``trial_days``, ``limits``,
            ``active``).
        sub: The newest subscription that may grant a plan, or None.
        now: Current time (UTC).

    Returns:
        The limits, with ``best`` taken from every active plan.

    Raises:
        PlanConfigError: When no default plan exists.
    """
    by_code = {p["code"]: p for p in plans}
    default = next((p for p in plans if p["is_default"]), None)
    if default is None:
        raise PlanConfigError("no default plan is loaded (make load-plans)")
    grant = _grants(sub, now)
    plan = default
    if grant == "paid" and sub is not None and sub["plan_code"] in by_code:
        plan = by_code[sub["plan_code"]]
    elif grant == "trial":
        plan = next((p for p in plans if p["trial_days"] > 0), default)
    best = best_of(p["limits"] for p in plans if p.get("active", True))
    return Limits(with_defaults(plan["limits"]), best, plan["code"], plan["name"])


def entitlements(conn: Connection, user_id: str, now: datetime) -> Limits:
    """Effective limits of ``user_id`` read from the database (uncached)."""
    return resolve_limits(repository.fetch_plans(conn),
                          repository.fetch_live_subscription(conn, user_id), now)  # fmt: skip


def cached_entitlements(
    cache: Any,  # noqa: ANN401 - redis.Redis
    user_id: str,
    load: Callable[[], Limits],
) -> Limits:
    """Limits from ``ent:{user_id}`` (60 s), else ``load()`` and store them.

    Redis errors fall back to ``load()``: gating never depends on the cache being up.
    """
    key = f"ent:{user_id}"
    try:
        raw = cache.get(key)
    except (RedisError, OSError):
        raw = None
    if raw:
        return Limits.from_cache(json.loads(raw))
    limits = load()
    with contextlib.suppress(RedisError, OSError):
        cache.set(key, json.dumps(limits.cache_json()), ex=ENT_TTL_SECONDS)
    return limits


def invalidate_entitlements(cache: Any, user_id: str) -> None:  # noqa: ANN401
    """Drop the cached limits after any plan, trial or subscription change (DD 4.1)."""
    cache.delete(f"ent:{user_id}")


# ---------------------------------------------------------------- trial and deletion (task 3.2)
def email_hash(email: str) -> str:
    """SHA-256 hex of the trimmed, lower-cased e-mail (``trial_claims.email_hash``)."""
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()


def start_trial(conn: Connection, user_id: str, email: str, now: datetime) -> bool:
    """Start the trial plan for ``trial_days`` days, once per e-mail ever (DD 4.3, 4.6).

    The trial plan is the active plan with ``trial_days > 0`` (never a code). Nothing is
    claimed when there is no trial plan or the user already has a live subscription, so a
    later verification can still use the claim. The claim row survives account deletion.

    Returns:
        True when the trial started.
    """
    plan = repository.fetch_trial_plan(conn)
    if plan is None or repository.fetch_open_subscription(conn, user_id) is not None:
        return False
    if not repository.claim_trial(conn, email_hash(email), user_id, now):
        return False
    ends = now + timedelta(days=int(plan["trial_days"]))
    repository.insert_trial_subscription(conn, user_id, str(plan["code"]), now, ends)
    return True


def paid_subscription_live(conn: Connection, user_id: str, now: datetime) -> bool:
    """Whether a paid (or manual) plan still grants access: deletion needs it cancelled first."""
    return _grants(repository.fetch_live_subscription(conn, user_id), now) == "paid"


def end_subscriptions(conn: Connection, user_id: str, now: datetime) -> None:
    """End every open subscription now, for account deletion (no refund; rows are kept).

    Paid ones become ``cancelled`` with the period ending now; a trial or open checkout
    becomes ``expired``. Cancelling at Razorpay arrives with checkout (task 3.3).
    """
    repository.end_open_subscriptions(conn, user_id, now)


def account_summary(conn: Connection, user_id: str, limits: Limits) -> dict[str, Any]:
    """The ``plan``, ``entitlements`` and ``subscription`` block of ``/me`` (DD 4.2)."""
    sub = repository.fetch_live_subscription(conn, user_id)
    block = None if sub is None else {
        "status": sub["status"], "plan_code": sub["plan_code"],
        "trial_ends_at": _iso(sub["trial_ends_at"]),
        "current_period_end": _iso(sub["current_period_end"]),
        "cancel_at_period_end": sub["cancel_at_period_end"],
        "grace_until": _iso(sub["grace_until"]), "pending_plan_code": sub["pending_plan_code"],
    }  # fmt: skip
    return {"plan": {"code": limits.plan_code, "name": limits.plan_name},
            "entitlements": limits.to_json(), "subscription": block}  # fmt: skip
