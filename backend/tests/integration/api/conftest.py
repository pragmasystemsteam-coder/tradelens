"""A migrated and seeded throwaway PostgreSQL for API tests (one per test module).

Never point TEST_DATABASE_URL at real data: the schema is reset to base for every module.
"""

import os

import pytest

URL = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture(scope="module")
def db(request):
    if not URL:
        pytest.skip("TEST_DATABASE_URL not set (needs PostgreSQL)")
    from alembic import command
    from alembic.config import Config
    from plans_util import RENAMED_PLANS, RENAMES, plans_doc, renamed
    from sqlalchemy import create_engine, text

    from tradelens.cli.seed import seed
    from tradelens.modules.billing.public import build_plan_rows, save_plan_rows

    repo = request.config.rootpath
    cfg = Config(str(repo / "backend" / "alembic.ini"))
    cfg.set_main_option("script_location", str(repo / "backend" / "migrations"))
    previous = os.environ.get("DATABASE_MIGRATION_URL")
    os.environ["DATABASE_MIGRATION_URL"] = URL
    try:
        command.downgrade(cfg, "base")
        command.upgrade(cfg, "head")
    finally:
        if previous is None:
            os.environ.pop("DATABASE_MIGRATION_URL", None)
        else:
            os.environ["DATABASE_MIGRATION_URL"] = previous
    eng = create_engine(URL)
    with eng.begin() as conn:
        seed(conn, repo / "config")
        if RENAMED_PLANS:  # task 2.10: same tests, renamed plan codes (FR-SUB-01)
            save_plan_rows(conn, build_plan_rows(renamed(plans_doc())))
            conn.execute(text("UPDATE plans SET active = false WHERE code = ANY(:old)"),
                         {"old": list(RENAMES)})  # fmt: skip
    yield eng
    eng.dispose()
