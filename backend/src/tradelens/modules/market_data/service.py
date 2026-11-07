"""Reference data for market data: calendars, instruments and series (FR-DATA-01, FR-DATA-09).

Business values come from config/*.json (NFR-18); this module validates them before they
reach the database so a typo cannot go live.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import Connection

from tradelens.modules.market_data import repository
from tradelens.modules.market_data.calendar import Calendar

TIMEFRAMES: tuple[str, ...] = ("5m", "15m", "1h", "4h", "1d")
ASSET_CLASSES = frozenset({"forex", "metal", "energy"})
MAX_PRICE_SCALE = 8
LAST_DOW = 6  # 0 = Sunday .. 6 = Saturday
HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

CALENDAR_KEYS = frozenset(
    {
        "code",
        "tz",
        "week_open_dow",
        "week_open_time",
        "week_close_dow",
        "week_close_time",
        "daily_break_start",
        "daily_break_end",
        "closures",
    }
)
INSTRUMENT_KEYS = frozenset(
    {
        "code",
        "display_name",
        "asset_class",
        "price_scale",
        "pip_scale",
        "normal_spread",
        "calendar_code",
        "sort_order",
    }
)

OPTIONAL_INSTRUMENT_KEYS = frozenset({"provider_symbols"})  # not stored; used by adapters (CR-004)
PROVIDERS = frozenset({"twelvedata", "oanda"})

Row = dict[str, Any]


class ReferenceDataError(ValueError):
    """Calendars or instruments config that must not be loaded."""


@dataclass(frozen=True, slots=True)
class ReferenceRows:
    """Rows for trading_calendars, instruments and series_status."""

    calendars: tuple[Row, ...]
    instruments: tuple[Row, ...]
    series_status: tuple[Row, ...]


def _check_keys(
    kind: str,
    item: Mapping[str, Any],
    expected: frozenset[str],
    optional: frozenset[str] = frozenset(),
) -> None:
    unknown, missing = set(item) - expected - optional, expected - set(item)
    if unknown or missing:
        raise ReferenceDataError(
            f"{kind} {item.get('code')!r}: unknown keys {sorted(unknown)}, "
            f"missing keys {sorted(missing)}"
        )


def _int(kind: str, code: str, name: str, value: object, low: int, high: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ReferenceDataError(f"{kind} {code!r}: {name} must be an integer")
    if value < low or (high is not None and value > high):
        raise ReferenceDataError(f"{kind} {code!r}: {name} must be an integer in [{low}, {high}]")
    return value


def _time(code: str, name: str, value: object, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not HHMM.match(value):
        raise ReferenceDataError(f"calendar {code!r}: {name} must be HH:MM")
    return value


def _calendar_row(item: Mapping[str, Any]) -> Row:
    _check_keys("calendar", item, CALENDAR_KEYS)
    code = item["code"]
    start = _time(code, "daily_break_start", item["daily_break_start"], optional=True)
    end = _time(code, "daily_break_end", item["daily_break_end"], optional=True)
    if (start is None) != (end is None):
        raise ReferenceDataError(f"calendar {code!r}: daily break needs both start and end")
    if not isinstance(item["closures"], list):
        raise ReferenceDataError(f"calendar {code!r}: closures must be a list")
    return {
        "code": code,
        "tz": item["tz"],
        "week_open_dow": _int(
            "calendar", code, "week_open_dow", item["week_open_dow"], 0, LAST_DOW
        ),
        "week_open_time": _time(code, "week_open_time", item["week_open_time"]),
        "week_close_dow": _int(
            "calendar", code, "week_close_dow", item["week_close_dow"], 0, LAST_DOW
        ),
        "week_close_time": _time(code, "week_close_time", item["week_close_time"]),
        "daily_break_start": start,
        "daily_break_end": end,
        "closures": list(item["closures"]),
    }


def _instrument_row(item: Mapping[str, Any], calendar_codes: set[str]) -> Row:
    _check_keys("instrument", item, INSTRUMENT_KEYS, OPTIONAL_INSTRUMENT_KEYS)
    code = item["code"]
    _provider_symbols(code, item.get("provider_symbols", {}))
    price_scale = _int("instrument", code, "price_scale", item["price_scale"], 0, MAX_PRICE_SCALE)
    pip_scale = _int("instrument", code, "pip_scale", item["pip_scale"], 0, price_scale)
    if item["asset_class"] not in ASSET_CLASSES:
        raise ReferenceDataError(
            f"instrument {code!r}: unknown asset_class {item['asset_class']!r}"
        )
    if item["calendar_code"] not in calendar_codes:
        raise ReferenceDataError(f"instrument {code!r}: unknown calendar {item['calendar_code']!r}")
    return {
        "code": code,
        "asset_class": item["asset_class"],
        "display_name": item["display_name"],
        "price_scale": price_scale,
        "pip_scale": pip_scale,
        "normal_spread": _int("instrument", code, "normal_spread", item["normal_spread"], 0),
        "calendar_code": item["calendar_code"],
        "sort_order": _int("instrument", code, "sort_order", item["sort_order"], 0),
        "active": True,
    }


def _provider_symbols(code: str, symbols: object) -> dict[str, str]:
    if not isinstance(symbols, Mapping) or not all(
        name in PROVIDERS and isinstance(value, str) and value.strip()
        for name, value in symbols.items()
    ):
        raise ReferenceDataError(
            f"instrument {code!r}: provider_symbols must map {sorted(PROVIDERS)} to symbols"
        )
    return dict(symbols)


def _unique(kind: str, rows: Sequence[Row]) -> None:
    codes = [row["code"] for row in rows]
    if len(codes) != len(set(codes)):
        raise ReferenceDataError(f"duplicate {kind} codes in config")


def build_reference_rows(
    calendars_doc: Mapping[str, Any], instruments_doc: Mapping[str, Any]
) -> ReferenceRows:
    """Validate calendars.json and instruments.json and turn them into table rows.

    Args:
        calendars_doc: Parsed ``{"calendars": [...]}``.
        instruments_doc: Parsed ``{"instruments": [...]}``.

    Returns:
        Calendar, instrument and series_status rows (one series per instrument and timeframe).

    Raises:
        ReferenceDataError: On unknown or missing keys, bad values, pip_scale > price_scale,
            unknown calendars or duplicate codes.
    """
    calendars = tuple(_calendar_row(item) for item in calendars_doc["calendars"])
    _unique("calendar", calendars)
    calendar_codes = {row["code"] for row in calendars}
    instruments = tuple(
        _instrument_row(item, calendar_codes) for item in instruments_doc["instruments"]
    )
    _unique("instrument", instruments)
    series = tuple(
        {"instrument": row["code"], "timeframe": timeframe}
        for row in instruments
        for timeframe in TIMEFRAMES
    )
    return ReferenceRows(calendars=calendars, instruments=instruments, series_status=series)


def save_reference_rows(conn: Connection, rows: ReferenceRows) -> None:
    """Insert reference rows; existing rows are left untouched (idempotent seed).

    Args:
        conn: Open connection inside the caller's transaction.
        rows: Rows from :func:`build_reference_rows`.
    """
    repository.insert_calendars(conn, rows.calendars)
    repository.insert_instruments(conn, rows.instruments)
    repository.insert_series_status(conn, rows.series_status)


@dataclass(frozen=True, slots=True)
class InstrumentSpec:
    """What the data pipeline needs to know about one instrument (from config/, validated)."""

    code: str
    price_scale: int
    pip_scale: int
    calendar: Calendar
    twelvedata_symbol: str | None


def load_instrument_specs(config_dir: Path) -> list[InstrumentSpec]:
    """Read and validate config/calendars.json and config/instruments.json.

    Args:
        config_dir: The repository ``config`` directory.

    Returns:
        One spec per instrument, in config order.

    Raises:
        ReferenceDataError: If the config is invalid (same checks as the seed).
    """
    calendars_doc = json.loads((config_dir / "calendars.json").read_text(encoding="utf-8"))
    instruments_doc = json.loads((config_dir / "instruments.json").read_text(encoding="utf-8"))
    rows = build_reference_rows(calendars_doc, instruments_doc)
    calendars = {row["code"]: Calendar.from_row(row) for row in calendars_doc["calendars"]}
    by_code = {item["code"]: item for item in instruments_doc["instruments"]}
    specs = []
    for row in rows.instruments:
        symbols = by_code[row["code"]].get("provider_symbols", {})
        specs.append(
            InstrumentSpec(
                code=row["code"],
                price_scale=row["price_scale"],
                pip_scale=row["pip_scale"],
                calendar=calendars[row["calendar_code"]],
                twelvedata_symbol=symbols.get("twelvedata"),
            )
        )
    return specs
