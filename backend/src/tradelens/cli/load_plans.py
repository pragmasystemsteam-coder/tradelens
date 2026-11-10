"""``make load-plans``: upsert config/plans.json into the database (DD 6.2; FR-SUB-01).

The file is validated before any connection is made, so a bad file never half-loads. Razorpay
plan IDs are taken for ``RAZORPAY_MODE`` (test by default).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

from tradelens.modules.billing.public import PlanRows, build_plan_rows, save_plan_rows

EXIT_OK, EXIT_FAILED = 0, 1
CONNECT_TIMEOUT_SECONDS = 5


def load_plan_rows(config_dir: Path, mode: str | None = None) -> PlanRows:
    """Read and validate ``config_dir/plans.json``.

    Raises:
        ValueError: If the file is invalid (PlanConfigError) or not JSON.
        OSError: If the file cannot be read.
    """
    doc = json.loads((config_dir / "plans.json").read_text(encoding="utf-8"))
    return build_plan_rows(doc, mode=mode or os.environ.get("RAZORPAY_MODE", "test") or "test")


def main(argv: list[str]) -> int:
    """Load plans into the database named by DATABASE_MIGRATION_URL (owner role).

    Args:
        argv: ``[CONFIG_DIR]`` (default ``config``).

    Returns:
        0 on success, 1 on an invalid file, a missing URL or a database error.
    """
    url = os.environ.get("DATABASE_MIGRATION_URL")
    if not url:
        sys.stderr.write("load-plans: set DATABASE_MIGRATION_URL (owner role)\n")
        return EXIT_FAILED
    config_dir = Path(argv[0]) if argv else Path("config")
    try:
        rows = load_plan_rows(config_dir)
    except (ValueError, KeyError, OSError) as exc:
        sys.stderr.write(f"load-plans: invalid {config_dir / 'plans.json'}: {exc}\n")
        return EXIT_FAILED
    engine = create_engine(url, connect_args={"connect_timeout": CONNECT_TIMEOUT_SECONDS})
    try:
        with engine.begin() as conn:
            save_plan_rows(conn, rows)
    except SQLAlchemyError as exc:
        sys.stderr.write(f"load-plans: failed ({type(exc).__name__}): {exc}\n")
        return EXIT_FAILED
    finally:
        engine.dispose()
    sys.stdout.write(f"load-plans: {len(rows.plans)} plans, {len(rows.prices)} prices loaded\n")
    return EXIT_OK
