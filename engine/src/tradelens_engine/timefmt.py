"""Exact, time-zone independent text form of UTC instants for JSON state and output."""

from __future__ import annotations

from datetime import UTC, datetime


def iso(dt: datetime) -> str:
    """``YYYY-MM-DDTHH:MM:SSZ`` (microseconds kept when present)."""
    text = dt.astimezone(UTC).isoformat()
    return text.replace("+00:00", "Z")


def parse_iso(text: str) -> datetime:
    """Inverse of :func:`iso`; always returns an aware UTC datetime."""
    return datetime.fromisoformat(text).astimezone(UTC)
