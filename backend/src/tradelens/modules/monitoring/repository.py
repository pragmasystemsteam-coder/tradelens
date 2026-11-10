"""SQL for health checks (DD 4.8)."""

from __future__ import annotations

from sqlalchemy import Connection, text

LAST_CHECK_AGE = text(
    "SELECT EXTRACT(EPOCH FROM (now() - max(last_checked_at))) FROM series_status"
)


def last_check_age(conn: Connection) -> float | None:
    """Seconds since the newest ``series_status.last_checked_at``; None before the first pass."""
    value = conn.execute(LAST_CHECK_AGE).scalar()
    return None if value is None else float(value)
