"""SQL for market data reference tables. Inserts never overwrite (ON CONFLICT DO NOTHING).

Instruments are never updated by the seed: changing price_scale under stored candles would
corrupt every price, so a correction is a deliberate migration, not a re-seed.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Connection, text

INSERT_CALENDAR = text(
    "INSERT INTO trading_calendars (code, tz, week_open_dow, week_open_time, week_close_dow,"
    " week_close_time, daily_break_start, daily_break_end, closures)"
    " VALUES (:code, :tz, :week_open_dow, CAST(:week_open_time AS time), :week_close_dow,"
    " CAST(:week_close_time AS time), CAST(:daily_break_start AS time),"
    " CAST(:daily_break_end AS time), CAST(:closures AS jsonb))"
    " ON CONFLICT (code) DO NOTHING"
)
INSERT_INSTRUMENT = text(
    "INSERT INTO instruments (code, asset_class, display_name, price_scale, pip_scale,"
    " normal_spread, calendar_code, sort_order, active)"
    " VALUES (:code, :asset_class, :display_name, :price_scale, :pip_scale, :normal_spread,"
    " :calendar_code, :sort_order, :active)"
    " ON CONFLICT (code) DO NOTHING"
)
INSERT_SERIES = text(
    "INSERT INTO series_status (instrument, timeframe) VALUES (:instrument, :timeframe)"
    " ON CONFLICT (instrument, timeframe) DO NOTHING"
)


def insert_calendars(conn: Connection, rows: Sequence[dict[str, Any]]) -> None:
    """Insert trading calendars (closures stored as jsonb)."""
    if rows:
        params = [{**row, "closures": json.dumps(row["closures"])} for row in rows]
        conn.execute(INSERT_CALENDAR, params)


def insert_instruments(conn: Connection, rows: Sequence[dict[str, Any]]) -> None:
    """Insert instruments."""
    if rows:
        conn.execute(INSERT_INSTRUMENT, list(rows))


def insert_series_status(conn: Connection, rows: Sequence[dict[str, Any]]) -> None:
    """Insert one series_status row per instrument and timeframe (55 in Release 1)."""
    if rows:
        conn.execute(INSERT_SERIES, list(rows))


INSTRUMENTS = text(
    "SELECT code, display_name, asset_class, price_scale, pip_scale FROM instruments"
    " WHERE active ORDER BY sort_order, code"
)
STATUS = text(
    "SELECT s.instrument, s.timeframe, s.status, s.last_candle_time, s.delayed_since,"
    " i.asset_class FROM series_status s JOIN instruments i ON i.code = s.instrument"
    " ORDER BY i.sort_order, s.instrument, s.timeframe"
)


def instrument_rows(conn: Connection) -> list[dict[str, Any]]:
    """Active instruments in display order (``/instruments``)."""
    return [dict(r) for r in conn.execute(INSTRUMENTS).mappings()]


def series_status_rows(conn: Connection) -> list[dict[str, Any]]:
    """Every series status with its instrument's asset class (``/status/data``)."""
    return [dict(r) for r in conn.execute(STATUS).mappings()]
