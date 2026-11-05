"""Trading day, week and session keys on New York time (Detailed Design 3.4, FR-DATA-04).

All derived from UTC instants through ZoneInfo('America/New_York'), so daylight saving
needs no special code. The trading day starts at 17:00 New York.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from tradelens_engine.types import require_aware

NY = ZoneInfo("America/New_York")
HHMM = re.compile(r"([01]\d|2[0-3]):([0-5]\d)")
DAY_SHIFT = timedelta(hours=7)  # 17:00 + 7 h = midnight, so 17:00 belongs to the next day
SESSION_ORDER: tuple[str, ...] = ("asian", "london", "new_york")
DEFAULT_SESSIONS: dict[str, tuple[str, str]] = {
    "asian": ("19:00", "03:00"),
    "london": ("03:00", "12:00"),
    "new_york": ("08:00", "17:00"),
}


def _to_ny(dt: datetime) -> datetime:
    return require_aware("dt", dt).astimezone(NY)


def parse_hhmm(hhmm: str) -> int:
    """Minutes after midnight of an "HH:MM" time (00:00 to 23:59).

    Args:
        hhmm: Time such as "19:00".

    Returns:
        Minutes after midnight.

    Raises:
        ValueError: If the text is not a valid HH:MM time.
    """
    match = HHMM.fullmatch(hhmm) if isinstance(hhmm, str) else None
    if match is None:
        raise ValueError(f"bad HH:MM value {hhmm!r}")
    return int(match.group(1)) * 60 + int(match.group(2))


def ny_day_key(dt: datetime) -> date:
    """Trading day: the New York local date of (local time + 7 h)."""
    return (_to_ny(dt) + DAY_SHIFT).date()


def ny_week_key(dt: datetime) -> str:
    """ISO week of the trading day, e.g. '2026-W46'."""
    year, week, _ = ny_day_key(dt).isocalendar()
    return f"{year}-W{week:02d}"


def sessions_of(
    open_time: datetime, sessions: Mapping[str, tuple[str, str]] = DEFAULT_SESSIONS
) -> tuple[str, ...]:
    """Sessions a candle belongs to, by the New York time of its open.

    London and New York overlap, so a candle can be in two sessions.

    Args:
        open_time: Aware open time of the candle.
        sessions: Session name to ("HH:MM", "HH:MM") New York start and end.

    Returns:
        Session names in the order asian, london, new_york.
    """
    local = _to_ny(open_time)
    minute = local.hour * 60 + local.minute
    result = []
    for name in SESSION_ORDER:
        if name not in sessions:
            continue
        start, end = (parse_hhmm(v) for v in sessions[name])
        inside = start <= minute < end if start < end else (minute >= start or minute < end)
        if inside:
            result.append(name)
    return tuple(result)
