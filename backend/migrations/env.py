"""Alembic environment: raw-SQL migrations run with the owner role (DATABASE_MIGRATION_URL)."""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)


def database_url() -> str:
    """Owner-role URL from the environment, else the ini file (offline SQL only)."""
    return (
        os.environ.get("DATABASE_MIGRATION_URL") or config.get_main_option("sqlalchemy.url") or ""
    )


def run_offline() -> None:
    """Emit SQL to stdout (or the configured buffer) without a database."""
    context.configure(url=database_url(), literal_binds=True, transaction_per_migration=True)
    with context.begin_transaction():
        context.run_migrations()


def run_online() -> None:
    """Apply migrations to the database, one transaction per migration."""
    engine = create_engine(database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_offline()
else:
    run_online()
