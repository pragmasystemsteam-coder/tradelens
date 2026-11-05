"""``make seed``: load config/*.json into the database, idempotently (Detailed Design 2.7, 6).

Seeds 2 trading calendars, 11 instruments, 55 series_status rows, rule version r1.0 and its
4 presets. Plans and prices (config/plans.json) are seeded with migration 0002 (DD-8).
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, create_engine
from sqlalchemy.exc import SQLAlchemyError

from tradelens.modules.analysis.public import RuleRows, build_rule_rows, save_rule_rows
from tradelens.modules.market_data.public import (
    ReferenceRows,
    build_reference_rows,
    save_reference_rows,
)

EXIT_OK, EXIT_FAILED = 0, 1
SEED_CONNECT_TIMEOUT_SECONDS = 5
Row = dict[str, Any]


@dataclass(frozen=True, slots=True)
class SeedRows:
    """Everything the seed writes, validated."""

    reference: ReferenceRows
    rules: RuleRows

    @property
    def calendars(self) -> tuple[Row, ...]:
        """trading_calendars rows."""
        return self.reference.calendars

    @property
    def instruments(self) -> tuple[Row, ...]:
        """Instruments rows."""
        return self.reference.instruments

    @property
    def series_status(self) -> tuple[Row, ...]:
        """series_status rows."""
        return self.reference.series_status

    @property
    def rule_versions(self) -> tuple[Row, ...]:
        """rule_versions rows."""
        return self.rules.rule_versions

    @property
    def presets(self) -> tuple[Row, ...]:
        """Presets rows."""
        return self.rules.presets


def _read_json(path: Path) -> Any:  # noqa: ANN401 - parsed JSON is untyped until validated
    return json.loads(path.read_text(encoding="utf-8"))


def load_seed_rows(config_dir: Path) -> SeedRows:
    """Read and validate every seed file without touching the database.

    Args:
        config_dir: The repository's config/ folder.

    Returns:
        The validated rows.

    Raises:
        ValueError: If any config file is invalid (ReferenceDataError or RuleConfigError).
    """
    reference = build_reference_rows(
        _read_json(config_dir / "calendars.json"), _read_json(config_dir / "instruments.json")
    )
    rule_files = sorted((config_dir / "rules").glob("*.json"))
    rules = build_rule_rows([_read_json(path) for path in rule_files])
    return SeedRows(reference=reference, rules=rules)


def write_seed_rows(conn: Connection, rows: SeedRows) -> None:
    """Write validated rows inside the caller's transaction; safe to run repeatedly.

    Args:
        conn: Connection with an open transaction (owner role).
        rows: Rows from :func:`load_seed_rows`.
    """
    save_reference_rows(conn, rows.reference)
    save_rule_rows(conn, rows.rules)


def seed(conn: Connection, config_dir: Path) -> None:
    """Validate config/ and write it inside the caller's transaction.

    Args:
        conn: Connection with an open transaction (owner role).
        config_dir: The repository's config/ folder.
    """
    write_seed_rows(conn, load_seed_rows(config_dir))


def main(argv: list[str]) -> int:
    """Seed the database named by DATABASE_MIGRATION_URL (owner role only).

    Config is validated before any connection is made, so a bad file never half-seeds.

    Args:
        argv: ``[CONFIG_DIR]`` (default ``config``).

    Returns:
        0 on success; 1 when the URL is missing, the config is invalid or the database fails.
    """
    url = os.environ.get("DATABASE_MIGRATION_URL")
    if not url:
        sys.stderr.write(
            "seed: set DATABASE_MIGRATION_URL (owner role; the app role must not seed)\n"
        )
        return EXIT_FAILED
    config_dir = Path(argv[0]) if argv else Path("config")
    try:
        rows = load_seed_rows(config_dir)
    except (ValueError, KeyError, OSError) as exc:
        sys.stderr.write(f"seed: invalid config in {config_dir}: {exc}\n")
        return EXIT_FAILED
    engine = create_engine(url, connect_args={"connect_timeout": SEED_CONNECT_TIMEOUT_SECONDS})
    try:
        with engine.begin() as conn:
            write_seed_rows(conn, rows)
    except (SQLAlchemyError, ValueError) as exc:
        sys.stderr.write(f"seed: failed ({type(exc).__name__}): {exc}\n")
        return EXIT_FAILED
    finally:
        engine.dispose()
    sys.stdout.write(f"seed: loaded {config_dir}\n")
    return EXIT_OK
