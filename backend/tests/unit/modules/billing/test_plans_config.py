"""Plan loader for config/plans.json (DD 6.2; CR-003, FR-SUB-01). No database needed."""

import copy
import json
from pathlib import Path

import pytest

from tradelens.modules.billing.public import LIMIT_KEYS, PlanConfigError, build_plan_rows

REPO = Path(__file__).resolve().parents[5]


@pytest.fixture
def doc():
    return json.loads((REPO / "config" / "plans.json").read_text(encoding="utf-8"))


def test_plans_rows_from_config(doc):
    rows = build_plan_rows(doc)
    assert [p["code"] for p in rows.plans] == ["free", "pro_monthly", "pro_annual",
                                                "pro_annual_founder"]  # fmt: skip
    assert len(rows.prices) == 6
    assert [p["code"] for p in rows.plans if p["is_default"]] == ["free"]
    assert [p["code"] for p in rows.plans if p["trial_days"] > 0] == ["pro_monthly"]
    assert rows.founder_slots == ({"plan_code": "pro_annual_founder", "cap": 100},)
    assert dict(rows.country_currency) == {"IN": "INR", "*": "USD"}
    founder = next(p for p in rows.plans if p["code"] == "pro_annual_founder")
    assert founder["renews_into"] == "pro_annual"
    assert founder["limits"] == doc["limit_sets"]["pro"]  # "@pro" resolved
    assert set(founder["limits"]) == set(LIMIT_KEYS)


def test_prices_in_minor_units_and_interval(doc):
    prices = {(p["plan_code"], p["currency"]): p for p in build_plan_rows(doc).prices}
    assert prices[("pro_monthly", "INR")]["amount_minor"] == 99900
    assert prices[("pro_annual", "USD")]["interval"] == "year"
    assert all(p["razorpay_plan_id"] is None for p in prices.values())  # none set yet


def test_razorpay_plan_ids_follow_mode(doc):
    doc["razorpay_plan_ids"] = {
        "test": {"pro_monthly:INR": "plan_T1"},
        "live": {"pro_monthly:INR": "plan_L1"},
    }
    for mode, expected in (("test", "plan_T1"), ("live", "plan_L1")):
        prices = {(p["plan_code"], p["currency"]): p["razorpay_plan_id"]
                  for p in build_plan_rows(doc, mode=mode).prices}  # fmt: skip
        assert prices[("pro_monthly", "INR")] == expected


def test_unknown_limit_key_fails_load(doc):
    doc["plans"][0]["limits"]["max_watchlist"] = 2  # typo: must not silently drop a limit
    with pytest.raises(PlanConfigError, match="max_watchlist"):
        build_plan_rows(doc)


def test_unknown_limit_key_in_limit_set_fails_load(doc):
    doc["limit_sets"]["pro"]["custom_setting"] = True
    with pytest.raises(PlanConfigError, match="custom_setting"):
        build_plan_rows(doc)


def test_two_trial_plans_fail_load(doc):
    doc["plans"][2]["trial_days"] = 15
    with pytest.raises(PlanConfigError, match="trial"):
        build_plan_rows(doc)


def _set(path, value):
    def mutate(d):
        target = d
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value

    return mutate


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (_set(["plans", 1, "is_default"], True), "default"),
        (_set(["plans", 0, "is_default"], False), "default"),
        (_set(["plans", 0, "limits", "max_watchlists"], "3"), "max_watchlists"),
        (_set(["plans", 0, "limits", "max_watchlists"], 1.5), "max_watchlists"),
        (_set(["plans", 0, "limits", "max_watchlists"], -1), "max_watchlists"),
        (_set(["plans", 0, "limits", "custom_settings"], 1), "custom_settings"),
        (_set(["plans", 0, "limits", "mtf_detail"], "half"), "mtf_detail"),
        (_set(["plans", 0, "limits", "asset_classes"], ["crypto"]), "asset_classes"),
        (_set(["plans", 1, "limits"], "@gold"), "@gold"),
        (_set(["plans", 3, "renews_into"], "nope"), "renews_into"),
        (_set(["plans", 1, "prices", "INR", "amount_minor"], 0), "amount_minor"),
        (_set(["plans", 1, "prices", "INR", "interval"], "week"), "interval"),
        (_set(["plans", 0, "prices"], {"INR": {"amount_minor": 1, "interval": "month"}}), "free"),
        (_set(["plans", 0, "colour"], "blue"), "colour"),
        (lambda d: d["plans"].append(copy.deepcopy(d["plans"][1])), "duplicate"),
        (lambda d: d["country_currency"].pop("*"), "default row"),
    ],
)
def test_invalid_config_fails_load(doc, mutate, match):
    mutate(doc)
    with pytest.raises(PlanConfigError, match=match):
        build_plan_rows(doc)


def test_null_count_means_unlimited(doc):
    doc["limit_sets"]["pro"]["max_alert_rules"] = None
    plans = build_plan_rows(doc).plans
    assert next(p for p in plans if p["code"] == "pro_annual")["limits"]["max_alert_rules"] is None


def test_missing_limit_key_is_allowed(doc):
    # DD 6.2 "Missing key means": entitlements apply the documented default (task 2.4).
    del doc["plans"][0]["limits"]["max_profiles"]
    free = build_plan_rows(doc).plans[0]
    assert "max_profiles" not in free["limits"]
