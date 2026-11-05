"""Database engine factory (SQLAlchemy 2, psycopg 3)."""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy import Engine, create_engine

CONNECT_TIMEOUT_SECONDS = 2  # health checks must answer within 2 s (Detailed Design 4.8)
MAX_CACHED_ENGINES = 4


@lru_cache(maxsize=MAX_CACHED_ENGINES)
def get_engine(url: str) -> Engine:
    """Return a pooled engine for ``url``, created once per process.

    Args:
        url: SQLAlchemy database URL.

    Returns:
        The shared engine.

    Raises:
        sqlalchemy.exc.ArgumentError: If the URL cannot be parsed.
    """
    return create_engine(
        url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": CONNECT_TIMEOUT_SECONDS},
    )
