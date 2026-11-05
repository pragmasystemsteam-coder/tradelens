"""Rule versions and presets (FR-CUST-04, FR-SMC-11, Detailed Design 2.5 and 6.3).

The settings hash of every preset is computed by the engine, so the database and the engine
always agree on which settings produced which events.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection

from tradelens.modules.analysis import repository
from tradelens_engine import Settings, SettingsError

PRESET_CODES = frozenset({"default", "scalping", "intraday", "swing"})
PERMILLE_TOTAL = 1000
SMALLINT_MAX = 32767
REQUIRED_RULE_KEYS = ("version", "scoring_version", "user", "constants", "weights", "presets")
REQUIRED_PRESET_KEYS = ("code", "name", "sort_order", "user")

Row = dict[str, Any]


class RuleConfigError(ValueError):
    """A rule version file that must not be loaded."""


@dataclass(frozen=True, slots=True)
class RuleRows:
    """Rows for rule_versions and presets."""

    rule_versions: tuple[Row, ...]
    presets: tuple[Row, ...]


def _require_ints(value: object, path: str) -> None:
    """Weights are integers only (DD-5): no floats, bools or strings anywhere in the tree."""
    if isinstance(value, Mapping):
        for key, item in value.items():
            _require_ints(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _require_ints(item, f"{path}[{index}]")
    elif type(value) is not int:
        raise RuleConfigError(f"{path} must be an integer (DD-5), got {value!r}")


def _require_keys(item: Mapping[str, Any], keys: Sequence[str], where: str) -> None:
    missing = [key for key in keys if key not in item]
    if missing:
        raise RuleConfigError(f"{where}: missing key(s) {missing}")


def _settings(version: str, user: Mapping[str, Any], constants: Mapping[str, Any]) -> Settings:
    try:
        return Settings.from_json({"user": dict(user), "constants": dict(constants)})
    except SettingsError as exc:
        raise RuleConfigError(f"{version}: {exc}") from exc


def _rule_rows(doc: Mapping[str, Any]) -> tuple[Row, list[Row]]:
    _require_keys(doc, REQUIRED_RULE_KEYS, f"rule file {doc.get('version', '?')}")
    version = doc["version"]
    official = _settings(version, doc["user"], doc["constants"])
    weights = doc["weights"]
    _require_ints(weights, f"{version}.weights")
    _require_keys(weights, ("q_permille", "c_permille"), f"{version}.weights")
    if weights["q_permille"] + weights["c_permille"] != PERMILLE_TOTAL:
        raise RuleConfigError(f"{version}: q_permille + c_permille must be {PERMILLE_TOTAL}")
    rule_row: Row = {
        "version": version,
        "settings": official.to_json(),
        "settings_hash": official.hash(version),
        "weights": {"scoring_version": doc["scoring_version"], **weights},
        "note": doc.get("note"),
    }
    presets = doc["presets"]
    for preset in presets:
        _require_keys(preset, REQUIRED_PRESET_KEYS, f"{version} preset {preset.get('code', '?')}")
        order = preset["sort_order"]
        if type(order) is not int or not 0 <= order <= SMALLINT_MAX:
            raise RuleConfigError(f"{version} preset {preset['code']}: sort_order out of range")
    if {p["code"] for p in presets} != PRESET_CODES or len(presets) != len(PRESET_CODES):
        raise RuleConfigError(f"{version}: presets must be exactly {sorted(PRESET_CODES)}")
    preset_rows: list[Row] = []
    for preset in presets:
        settings = _settings(version, preset["user"], doc["constants"])
        if preset["code"] == "default" and settings.user_json() != official.user_json():
            raise RuleConfigError(f"{version}: the default preset must equal the official settings")
        preset_rows.append(
            {
                "rule_version": version,
                "code": preset["code"],
                "name": preset["name"],
                "settings": settings.user_json(),
                "settings_hash": settings.hash(version),
                "sort_order": preset["sort_order"],
            }
        )
    return rule_row, preset_rows


def build_rule_rows(rule_docs: Sequence[Mapping[str, Any]]) -> RuleRows:
    """Validate rule version files (config/rules/*.json) and turn them into table rows.

    Args:
        rule_docs: Parsed rule version documents, oldest first.

    Returns:
        One rule_versions row per document and its four presets.

    Raises:
        RuleConfigError: On settings outside the allowed values, floats, wrong weights,
            a missing preset or a default preset that differs from the official settings.
    """
    versions: list[Row] = []
    presets: list[Row] = []
    for doc in rule_docs:
        rule_row, preset_rows = _rule_rows(doc)
        versions.append(rule_row)
        presets.extend(preset_rows)
    return RuleRows(rule_versions=tuple(versions), presets=tuple(presets))


def save_rule_rows(conn: Connection, rows: RuleRows) -> None:
    """Insert rule versions and presets; activate the newest only if none is active.

    An existing rule version is never overwritten (the rule_versions_guard trigger also
    forbids it), so published results stay reproducible (FR-SMC-11).

    Args:
        conn: Open connection inside the caller's transaction.
        rows: Rows from :func:`build_rule_rows`.
    """
    repository.insert_rule_versions(conn, rows.rule_versions)
    repository.insert_presets(conn, rows.presets)
    _check_no_drift(conn, rows)
    if rows.rule_versions:
        repository.activate_if_none_active(conn, rows.rule_versions[-1]["version"])


def _check_no_drift(conn: Connection, rows: RuleRows) -> None:
    """Fail when config/rules differs from what is already stored for the same version.

    ON CONFLICT DO NOTHING keeps the stored row, so an edited rule file would otherwise be
    silently ignored. A change to rules needs a new rule version (FR-SMC-11).
    """
    versions = [row["version"] for row in rows.rule_versions]
    stored = repository.fetch_rule_hashes(conn, versions)
    for row in rows.rule_versions:
        if stored.get(row["version"]) != row["settings_hash"]:
            raise RuleConfigError(
                f"{row['version']}: config/rules differs from the stored rule version;"
                " publish a new version instead of editing a released one"
            )
    stored_presets = repository.fetch_preset_hashes(conn, versions)
    for preset in rows.presets:
        if stored_presets.get((preset["rule_version"], preset["code"])) != preset["settings_hash"]:
            raise RuleConfigError(
                f"{preset['rule_version']}: preset {preset['code']} differs from the stored preset"
            )
