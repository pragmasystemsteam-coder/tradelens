"""Engine settings, allowed values and the settings hash (Detailed Design 3.3)."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from tradelens_engine.timekeys import SESSION_ORDER, parse_hhmm

ALLOWED_VALUES: dict[str, tuple[Any, ...]] = {
    "internal_pivot": (None, 2, 3, 5),
    "external_pivot": (8, 10, 15, 20),
    "fvg_min_m": (0, 250, 500, 1000),
    "eq_tol_m": (50, 100, 200),
    "displacement": ("normal", "strong"),
    "zone_max_age": (50, 100, 200),
    "zone_max_retests": (1, 2, 3),
    "counter_trend": ("warn", "hide"),
}
USER_KEYS: tuple[str, ...] = tuple(ALLOWED_VALUES)
INT_CONSTANTS: tuple[str, ...] = (
    "bos_buffer_m",
    "sweep_window_bars",
    "ob_lookback",
    "disp_break_window",
    "level_max_age",
    "atr_period",
    "body_ratio_permille",
)
CONSTANT_KEYS = frozenset((*INT_CONSTANTS, "sweep_reclaim", "displacement", "sessions_ny"))
SWEEP_RECLAIM_VALUES = ("same_candle",)
DISPLACEMENT_KEYS = frozenset({"single_m", "multi_m"})
HIGHER_TIMEFRAMES = ("4h", "1d")


class SettingsError(ValueError):
    """Settings JSON that is not allowed by the active rule version."""


def settings_hash(rule_version: str, user: Mapping[str, Any], constants: Mapping[str, Any]) -> str:
    """SHA-256 of the canonical settings JSON plus rule version (64 hex characters)."""
    canonical = json.dumps(
        {"rule_version": rule_version, "settings": user, "constants": constants},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _is_allowed(value: object, allowed: tuple[object, ...]) -> bool:
    # Exact type match: True == 1 and 3.0 == 3 must not slip through.
    return any(type(value) is type(option) and value == option for option in allowed)


def _reject_floats(value: object, path: str) -> None:
    if isinstance(value, float):
        raise SettingsError(f"float not allowed at {path}")
    if isinstance(value, Mapping):
        for key, item in value.items():
            _reject_floats(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_floats(item, f"{path}[{index}]")


def _validate_displacement(table: object) -> None:
    levels = ALLOWED_VALUES["displacement"]
    if not isinstance(table, Mapping) or set(table) != set(levels):
        raise SettingsError(f"constants.displacement must have exactly the levels {levels}")
    for level in levels:
        row = table[level]
        if not isinstance(row, Mapping) or set(row) != DISPLACEMENT_KEYS:
            raise SettingsError(f"constants.displacement.{level} needs {sorted(DISPLACEMENT_KEYS)}")
        for key in DISPLACEMENT_KEYS:
            if type(row[key]) is not int or row[key] <= 0:
                raise SettingsError(f"constants.displacement.{level}.{key} must be a positive int")


def _validate_sessions(sessions: object) -> None:
    if not isinstance(sessions, Mapping) or set(sessions) != set(SESSION_ORDER):
        raise SettingsError(f"constants.sessions_ny must have exactly {SESSION_ORDER}")
    for name in SESSION_ORDER:
        window = sessions[name]
        if not isinstance(window, (list, tuple)) or len(window) != len(("start", "end")):
            raise SettingsError(f"constants.sessions_ny.{name} must be [start, end]")
        try:
            for value in window:
                parse_hhmm(value)
        except ValueError as exc:
            raise SettingsError(f"constants.sessions_ny.{name}: {exc}") from exc


def _validate_constants(constants: Mapping[str, Any]) -> None:
    """Check the rule constants: exact keys, integer types, session and displacement tables."""
    _reject_floats(constants, "constants")
    unknown = sorted(set(constants) - CONSTANT_KEYS)
    missing = sorted(CONSTANT_KEYS - set(constants))
    if unknown or missing:
        raise SettingsError(f"constants: unknown {unknown}, missing {missing}")
    for key in INT_CONSTANTS:
        if type(constants[key]) is not int or constants[key] < 0:
            raise SettingsError(f"constants.{key} must be a non-negative int")
    if constants["sweep_reclaim"] not in SWEEP_RECLAIM_VALUES:
        raise SettingsError(f"constants.sweep_reclaim must be one of {SWEEP_RECLAIM_VALUES}")
    _validate_displacement(constants["displacement"])
    _validate_sessions(constants["sessions_ny"])


@dataclass(frozen=True, slots=True)
class Settings:
    """User-adjustable settings (validated against ALLOWED_VALUES) plus rule constants."""

    internal_pivot: int | None
    external_pivot: int
    fvg_min_m: int
    eq_tol_m: int
    displacement: str
    zone_max_age: int
    zone_max_retests: int
    counter_trend: str
    constants: Mapping[str, Any]

    @classmethod
    def from_json(cls, obj: Mapping[str, Any]) -> Settings:
        """Parse and validate settings JSON (FR-CUST-02: fixed lists of approved values).

        Args:
            obj: ``{"user": {...}, "constants": {...}}``.

        Returns:
            The validated, immutable settings.

        Raises:
            SettingsError: On unknown, missing or unlisted values, wrong types or floats.
        """
        if not isinstance(obj, Mapping) or set(obj) != {"user", "constants"}:
            raise SettingsError('settings must have exactly the keys "user" and "constants"')
        user, constants = obj["user"], obj["constants"]
        if not isinstance(user, Mapping) or not isinstance(constants, Mapping):
            raise SettingsError('"user" and "constants" must be objects')
        unknown = sorted(set(user) - set(USER_KEYS))
        missing = sorted(set(USER_KEYS) - set(user))
        if unknown:
            raise SettingsError(f"unknown setting(s): {', '.join(unknown)}")
        if missing:
            raise SettingsError(f"missing setting(s): {', '.join(missing)}")
        for key in USER_KEYS:
            if not _is_allowed(user[key], ALLOWED_VALUES[key]):
                raise SettingsError(f"{key}: {user[key]!r} is not one of {ALLOWED_VALUES[key]}")
        _validate_constants(constants)
        return cls(
            **{key: user[key] for key in USER_KEYS}, constants=copy.deepcopy(dict(constants))
        )

    def user_json(self) -> dict[str, Any]:
        """Return the user-adjustable settings as a plain dict."""
        return {key: getattr(self, key) for key in USER_KEYS}

    def to_json(self) -> dict[str, Any]:
        """Return ``{"user": ..., "constants": ...}``, the form stored in rule_versions."""
        return {"user": self.user_json(), "constants": copy.deepcopy(dict(self.constants))}

    def hash(self, rule_version: str) -> str:
        """Return the settings hash for ``rule_version`` (stored on every engine output row)."""
        return settings_hash(rule_version, self.user_json(), self.constants)

    def internal_pivot_for(self, timeframe: str) -> int:
        """Internal pivot length: the user value, or 3 (5 on 4h and 1d) when unset."""
        if self.internal_pivot is not None:
            return self.internal_pivot
        return 5 if timeframe in HIGHER_TIMEFRAMES else 3
