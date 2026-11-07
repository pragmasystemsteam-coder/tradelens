"""Ingest schedule: every 5-minute boundary plus a small offset (DD 8.1 task 1.9)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
DEFAULT_PERIOD_SECONDS = 300


def next_run_at(
    now: datetime, period_s: int = DEFAULT_PERIOD_SECONDS, offset_s: int = 2
) -> datetime:
    """The first ``boundary + offset`` strictly after ``now``.

    Args:
        now: Current UTC time.
        period_s: Boundary period in seconds (300 = every 5 minutes).
        offset_s: Seconds after the boundary (SCHEDULER_OFFSET_SECONDS), so the candle that
            just closed is available from the provider.

    Returns:
        The next run time.
    """
    period = timedelta(seconds=period_s)
    run = now - (now - EPOCH) % period + timedelta(seconds=offset_s)
    return run if run > now else run + period
