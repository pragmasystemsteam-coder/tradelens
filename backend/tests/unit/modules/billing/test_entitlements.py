"""entitlements(user) from limit keys only (DD 4.3, 7.4; task 2.4; FR-SUB-01, FR-SUB-12)."""

from datetime import UTC, datetime, timedelta

import pytest
from fake_redis import FakeRedis
from plans_util import RENAMES, plans_doc, renamed

from tradelens.core.errors import ApiError
from tradelens.core.limits import Limits
from tradelens.modules.billing.public import (
    build_plan_rows,
    cached_entitlements,
    invalidate_entitlements,
    resolve_limits,
)

NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
DAY = timedelta(days=1)


@pytest.fixture(params=["seed", "renamed"])
def plans(request, config_dir):
    doc = plans_doc()
    doc = doc if request.param == "seed" else renamed(doc)
    codes = {"seed": dict(zip(RENAMES, RENAMES, strict=True)), "renamed": RENAMES}[request.param]
    return list(build_plan_rows(doc).plans), codes


def sub(code, status="active", **times):
    return {"plan_code": code, "status": status, "trial_ends_at": times.get("trial_ends_at"),
            "current_period_end": times.get("current_period_end"),
            "grace_until": times.get("grace_until")}  # fmt: skip


def test_entitlements_default_plan_when_no_subscription(plans):
    rows, codes = plans
    lim = resolve_limits(rows, None, NOW)
    assert lim.plan_code == codes["free"]
    assert lim.asset_classes == ("forex",)
    assert lim["chart_history_candles"] == 500
    assert lim["max_watchlists"] == 1
    assert not lim.mtf_full


def test_entitlements_manual_pro(plans):
    rows, codes = plans
    lim = resolve_limits(rows, sub(codes["pro_monthly"]), NOW)
    assert lim.plan_code == codes["pro_monthly"]
    assert set(lim.asset_classes) == {"forex", "metal", "energy"}
    assert lim["chart_history_candles"] == 2000
    assert lim.mtf_full
    assert lim["max_watchlists"] == 3


def test_entitlements_from_limits_only(config_dir):
    """Renaming every plan code gives the same limits for the same situations."""
    seed_rows = build_plan_rows(plans_doc()).plans
    renamed_rows = build_plan_rows(renamed(plans_doc())).plans
    cases = [
        (None, None),
        (sub("pro_monthly"), sub("plus_m")),
        (sub("pro_annual", "cancelled", current_period_end=NOW + DAY),
         sub("plus_y", "cancelled", current_period_end=NOW + DAY)),
        (sub("pro_monthly", "trialing", trial_ends_at=NOW - DAY),
         sub("plus_m", "trialing", trial_ends_at=NOW - DAY)),
    ]  # fmt: skip
    for a, b in cases:
        got = resolve_limits(renamed_rows, b, NOW).values
        assert resolve_limits(seed_rows, a, NOW).values == got


def test_trial_grace_and_cancelled_follow_their_dates(plans):
    rows, codes = plans
    pro = codes["pro_monthly"]
    assert resolve_limits(rows, sub(pro, "trialing", trial_ends_at=NOW + DAY), NOW).mtf_full
    assert not resolve_limits(rows, sub(pro, "trialing", trial_ends_at=NOW - DAY), NOW).mtf_full
    assert resolve_limits(rows, sub(pro, "grace", grace_until=NOW + DAY), NOW).mtf_full
    assert not resolve_limits(rows, sub(pro, "grace", grace_until=NOW - DAY), NOW).mtf_full
    assert resolve_limits(rows, sub(pro, "cancelled", current_period_end=NOW + DAY), NOW).mtf_full
    assert not resolve_limits(rows, sub(pro, "expired"), NOW).mtf_full


def test_free_over_a_limit_pro_raises_gets_plan_required(plans):
    rows, codes = plans
    free = resolve_limits(rows, None, NOW)
    with pytest.raises(ApiError) as err:
        free.require_room("max_watchlists", 1)
    assert (err.value.status, err.value.code) == (403, "plan_required")
    assert err.value.details == {"limit_key": "max_watchlists", "limit": 1, "current": 1,
                                 "upgrade": True}  # fmt: skip
    with pytest.raises(ApiError) as err:
        free.require_asset("metal")
    assert err.value.code == "plan_required"
    pro = resolve_limits(rows, sub(codes["pro_annual"]), NOW)
    with pytest.raises(ApiError) as err:
        pro.require_room("max_watchlists", 3)
    assert (err.value.status, err.value.code) == (422, "plan_limit")
    pro.require_asset("energy")


def test_entitlements_cached_60s_and_invalidated(plans):
    rows, _ = plans
    redis = FakeRedis(clock=lambda: NOW.timestamp())
    calls = []

    def load():
        calls.append(1)
        return resolve_limits(rows, None, NOW)

    first = cached_entitlements(redis, "u1", load)
    again = cached_entitlements(redis, "u1", load)
    assert isinstance(again, Limits) and again.values == first.values
    assert len(calls) == 1
    assert 0 < redis.ttl("ent:u1") <= 60
    invalidate_entitlements(redis, "u1")
    cached_entitlements(redis, "u1", load)
    assert len(calls) == 2
