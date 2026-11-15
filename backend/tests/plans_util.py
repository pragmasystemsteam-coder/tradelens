"""plans.json with every plan code renamed (FR-SUB-01: no plan code is hard-coded).

``TL_RENAMED_PLANS=1`` makes the API integration tests load this file instead of the seed's
plans (task 2.10: the 2.4-2.7 gating tests must pass unchanged).
"""

import copy
import json
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RENAMES = {"free": "starter", "pro_monthly": "plus_m", "pro_annual": "plus_y",
           "pro_annual_founder": "plus_founder"}  # fmt: skip
RENAMED_PLANS = os.environ.get("TL_RENAMED_PLANS") == "1"


def plans_doc():
    return json.loads((REPO / "config" / "plans.json").read_text(encoding="utf-8"))


def renamed(doc):
    """A copy of ``doc`` with renamed codes and names."""
    out = copy.deepcopy(doc)
    for plan in out["plans"]:
        plan["code"] = RENAMES[plan["code"]]
        plan["name"] = "Renamed " + plan["name"]
        if plan.get("renews_into"):
            plan["renews_into"] = RENAMES[plan["renews_into"]]
    ids = out.get("razorpay_plan_ids", {})
    for mode, mapping in ids.items():
        ids[mode] = {RENAMES[k.split(":")[0]] + ":" + k.split(":")[1]: v
                     for k, v in mapping.items()}  # fmt: skip
    return out


def plan_code(seed_code):
    """The code the tests should use for a seed plan code in this run."""
    return RENAMES[seed_code] if RENAMED_PLANS else seed_code


def plan_name(seed_name):
    """The plan name the tests should expect in this run."""
    return "Renamed " + seed_name if RENAMED_PLANS else seed_name
