"""SQL for rule versions and presets. Inserts never overwrite (ON CONFLICT DO NOTHING)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Connection, text

INSERT_RULE_VERSION = text(
    "INSERT INTO rule_versions (version, settings, settings_hash, weights, note)"
    " VALUES (:version, CAST(:settings AS jsonb), :settings_hash, CAST(:weights AS jsonb), :note)"
    " ON CONFLICT (version) DO NOTHING"
)
INSERT_PRESET = text(
    "INSERT INTO presets (rule_version, code, name, settings, settings_hash, sort_order)"
    " VALUES (:rule_version, :code, :name, CAST(:settings AS jsonb), :settings_hash, :sort_order)"
    " ON CONFLICT (rule_version, code) DO NOTHING"
)
ACTIVATE_IF_NONE = text(
    "UPDATE rule_versions SET is_active = true WHERE version = :version"
    " AND NOT EXISTS (SELECT 1 FROM rule_versions WHERE is_active)"
)


def insert_rule_versions(conn: Connection, rows: Sequence[dict[str, Any]]) -> None:
    """Insert rule versions (settings and weights as jsonb)."""
    params = [
        {**row, "settings": json.dumps(row["settings"]), "weights": json.dumps(row["weights"])}
        for row in rows
    ]
    if params:
        conn.execute(INSERT_RULE_VERSION, params)


def insert_presets(conn: Connection, rows: Sequence[dict[str, Any]]) -> None:
    """Insert presets (settings as jsonb)."""
    params = [{**row, "settings": json.dumps(row["settings"])} for row in rows]
    if params:
        conn.execute(INSERT_PRESET, params)


SELECT_RULE_HASHES = text(
    "SELECT version, settings_hash FROM rule_versions WHERE version = ANY(:versions)"
)
SELECT_PRESET_HASHES = text(
    "SELECT rule_version, code, settings_hash FROM presets WHERE rule_version = ANY(:versions)"
)


def fetch_rule_hashes(conn: Connection, versions: Sequence[str]) -> dict[str, str]:
    """Stored settings hash per rule version."""
    rows = conn.execute(SELECT_RULE_HASHES, {"versions": list(versions)})
    return {row.version: row.settings_hash for row in rows}


def fetch_preset_hashes(conn: Connection, versions: Sequence[str]) -> dict[tuple[str, str], str]:
    """Stored settings hash per (rule version, preset code)."""
    rows = conn.execute(SELECT_PRESET_HASHES, {"versions": list(versions)})
    return {(row.rule_version, row.code): row.settings_hash for row in rows}


def activate_if_none_active(conn: Connection, version: str) -> None:
    """Mark ``version`` active unless another version already is (one active at a time)."""
    conn.execute(ACTIVATE_IF_NONE, {"version": version})


SELECT_ACTIVE = text("SELECT version, settings, weights FROM rule_versions WHERE is_active")


def fetch_active_rule(conn: Connection) -> tuple[str, dict[str, Any], dict[str, Any]] | None:
    """``(version, settings, weights)`` of the active rule version, or None."""
    row = conn.execute(SELECT_ACTIVE).first()
    return None if row is None else (row.version, dict(row.settings), dict(row.weights))
