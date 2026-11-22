"""Public interface of billing for other modules and the CLI (ADR-0001 section 4)."""

from tradelens.modules.billing.service import (
    LIMIT_KEYS,
    PlanConfigError,
    PlanRows,
    account_summary,
    build_plan_rows,
    cached_entitlements,
    create_manual_subscription,
    email_hash,
    end_subscriptions,
    entitlements,
    invalidate_entitlements,
    paid_subscription_live,
    plan_is_default,
    resolve_limits,
    save_plan_rows,
    start_trial,
)

__all__ = [
    "LIMIT_KEYS",
    "PlanConfigError",
    "PlanRows",
    "account_summary",
    "build_plan_rows",
    "cached_entitlements",
    "create_manual_subscription",
    "email_hash",
    "end_subscriptions",
    "entitlements",
    "invalidate_entitlements",
    "paid_subscription_live",
    "plan_is_default",
    "resolve_limits",
    "save_plan_rows",
    "start_trial",
]
