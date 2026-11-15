"""Plans, prices and limits from config/plans.json (DD 2.2, 6.2; CR-003, FR-SUB-01, DD-2).

Plans are data: any number of plans, exactly one default plan (the limits of a user without a
live subscription) and at most one trial plan (found by ``trial_days > 0``, never by code).
Limit keys are a closed list; an unknown key fails the load, so a typo cannot silently remove
a limit. A missing key is allowed and means the documented default (applied by entitlements,
task 2.4). ``null`` for a count means unlimited.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection

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
