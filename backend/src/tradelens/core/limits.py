"""Effective plan limits of a user and the gating checks (DD 4.3, 6.2; FR-SUB-01, FR-SUB-12).

Code reads limit keys only, never plan codes. ``Limits.best`` holds the most any active plan
offers per key, so a check can answer 403 ``plan_required`` with ``upgrade: true`` when a plan
offers more, and 422 ``plan_limit`` when none does (DD 4.3).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from tradelens.core.errors import ApiError

# DD 6.2 "missing key means": the most restrictive value.
DEFAULTS: dict[str, Any] = {
    "asset_classes": ["forex"],
    "mtf_detail": "strip",
    "chart_history_candles": 500,
    "max_watchlists": 1,
    "max_watchlist_items": 11,
    "max_alert_rules": 3,
    "custom_settings": False,
    "max_profiles": 0,
    "custom_watchlist_pairs_max": 0,
}
COUNT_KEYS = ("chart_history_candles", "max_watchlists", "max_watchlist_items",
              "max_alert_rules", "max_profiles", "custom_watchlist_pairs_max")  # fmt: skip
MTF_RANK = {"strip": 0, "full": 1}


def with_defaults(limits: Mapping[str, Any]) -> dict[str, Any]:
    """Limits with every documented key present (unknown keys are dropped)."""
    return {k: limits.get(k, v) for k, v in DEFAULTS.items()}


def _more(key: str, a: Any, b: Any) -> bool:  # noqa: ANN401 - limit values are JSON values
    """Whether value ``a`` offers more than ``b`` for ``key`` (None counts are unlimited)."""
    if key in COUNT_KEYS:
        return b is not None and (a is None or a > b)
    if key == "asset_classes":
        return bool(set(a) - set(b))
    if key == "mtf_detail":
        return MTF_RANK.get(a, 0) > MTF_RANK.get(b, 0)
    return bool(a) and not bool(b)


def best_of(all_limits: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """The most each key offers across plans (asset classes are united)."""
    best = dict(DEFAULTS)
    best["asset_classes"] = list(DEFAULTS["asset_classes"])
    for raw in all_limits:
        lim = with_defaults(raw)
        for key, value in lim.items():
            if key == "asset_classes":
                best[key] = sorted(set(best[key]) | set(value))
            elif _more(key, value, best[key]):
                best[key] = value
    return best


@dataclass(frozen=True, slots=True)
class Limits:
    """A user's effective limits.

    Attributes:
        values: Every limit key with its effective value.
        best: Every key with the most any active plan offers.
        plan_code: Code of the plan the limits come from (display only, never for gating).
        plan_name: Its name.
    """

    values: Mapping[str, Any]
    best: Mapping[str, Any] = field(default_factory=lambda: dict(DEFAULTS))
    plan_code: str = ""
    plan_name: str = ""

    def __getitem__(self, key: str) -> Any:  # noqa: ANN401 - JSON value of a limit key
        return self.values[key]

    @property
    def asset_classes(self) -> tuple[str, ...]:
        """Asset classes the user may see."""
        return tuple(self.values["asset_classes"])

    def allows_asset(self, asset_class: str) -> bool:
        """Whether ``asset_class`` is entitled (commodities are Pro-only in the seed)."""
        return asset_class in self.values["asset_classes"]

    @property
    def mtf_full(self) -> bool:
        """Whether higher-timeframe zones and the C breakdown are shown (FR-CHART-03)."""
        return bool(self.values["mtf_detail"] == "full")

    def upgrade_for(self, key: str) -> bool:
        """Whether some active plan offers more of ``key`` than the user has."""
        return _more(key, self.best[key], self.values[key])

    def denied(self, key: str, current: Any = None) -> ApiError:  # noqa: ANN401
        """403 ``plan_required`` (a plan offers more) or 422 ``plan_limit`` (none does)."""
        limit = self.values[key]
        details = {"limit_key": key, "limit": limit, "current": current}
        if self.upgrade_for(key):
            return ApiError(403, "plan_required", "Upgrade to use this feature",
                            {**details, "upgrade": True})  # fmt: skip
        return ApiError(422, "plan_limit", "Plan limit reached", {**details, "upgrade": False})

    def require_asset(self, asset_class: str) -> None:
        """Raise unless ``asset_class`` is entitled."""
        if not self.allows_asset(asset_class):
            raise self.denied("asset_classes", asset_class)

    def require_flag(self, key: str) -> None:
        """Raise unless the boolean limit ``key`` is on."""
        if not self.values[key]:
            raise self.denied(key, False)

    def require_room(self, key: str, current: int) -> None:
        """Raise when one more item would exceed the count limit ``key`` (None: unlimited)."""
        limit = self.values[key]
        if limit is not None and current >= limit:
            raise self.denied(key, current)

    def to_json(self) -> dict[str, Any]:
        """The ``entitlements`` object of ``/me`` and ``/auth/login``."""
        return {k: (list(v) if isinstance(v, list | tuple) else v) for k, v in self.values.items()}

    def cache_json(self) -> dict[str, Any]:
        """Everything needed to rebuild the object from the ``ent:{user_id}`` cache."""
        return {"values": self.to_json(), "best": dict(self.best), "plan_code": self.plan_code,
                "plan_name": self.plan_name}  # fmt: skip

    @classmethod
    def from_cache(cls, doc: Mapping[str, Any]) -> Limits:
        """Inverse of :meth:`cache_json`."""
        return cls(with_defaults(doc["values"]), dict(doc["best"]), doc["plan_code"],
                   doc["plan_name"])  # fmt: skip
