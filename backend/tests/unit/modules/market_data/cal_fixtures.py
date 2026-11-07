"""Shared calendars for market-data tests (same values as config/calendars.json)."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from tradelens.modules.market_data.calendar import Calendar

NY = ZoneInfo("America/New_York")
FX = Calendar.from_row(
    {
        "code": "fx_24x5",
        "tz": "America/New_York",
        "week_open_dow": 0,
        "week_open_time": "17:00",
        "week_close_dow": 5,
        "week_close_time": "17:00",
        "daily_break_start": None,
        "daily_break_end": None,
        "closures": [],
    }
)
METAL = Calendar.from_row(
    {
        "code": "metal_energy_break",
        "tz": "America/New_York",
        "week_open_dow": 0,
        "week_open_time": "18:00",
        "week_close_dow": 5,
        "week_close_time": "17:00",
        "daily_break_start": "17:00",
        "daily_break_end": "18:00",
        "closures": [],
    }
)


def ny(*args: int) -> datetime:
    """A New York wall-clock time as a UTC instant."""
    return datetime(*args, tzinfo=NY).astimezone(UTC)
