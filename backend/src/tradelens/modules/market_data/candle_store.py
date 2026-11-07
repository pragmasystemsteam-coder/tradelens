"""PostgreSQL implementation of the ingest ``CandleStore`` (candles, series_status, data_gaps).

All SQL for candles lives here and in ``repository.py``. Candles are append-only: an insert
never overwrites a stored candle (``ON CONFLICT DO NOTHING``).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import Connection, text

from tradelens.modules.market_data.candles import StoredCandle
from tradelens.modules.market_data.ingest import SeriesStatus

INSERT_CANDLE = text(
    "INSERT INTO candles (instrument, timeframe, open_time, o, h, l, c, bid_o, bid_h, bid_l,"
    " bid_c, ask_o, ask_h, ask_l, ask_c, tick_volume, source)"
    " VALUES (:instrument, :timeframe, :open_time, :o, :h, :l, :c, :bid_o, :bid_h, :bid_l,"
    " :bid_c, :ask_o, :ask_h, :ask_l, :ask_c, :tick_volume, :source)"
    " ON CONFLICT (instrument, timeframe, open_time) DO NOTHING"
)
LAST_OPEN = text("SELECT max(open_time) FROM candles WHERE instrument = :i AND timeframe = :tf")
OPEN_TIMES = text(
    "SELECT open_time FROM candles WHERE instrument = :i AND timeframe = :tf"
    " AND open_time >= :since ORDER BY open_time"
)
LOAD = text(
    "SELECT instrument, timeframe, open_time, o, h, l, c, bid_o, bid_h, bid_l, bid_c,"
    " ask_o, ask_h, ask_l, ask_c, tick_volume, source FROM candles"
    " WHERE instrument = :i AND timeframe = :tf"
    " AND (CAST(:since AS timestamptz) IS NULL OR open_time >= :since) ORDER BY open_time"
)
GET_STATUS = text(
    "SELECT status, last_candle_time, delayed_since, last_checked_at FROM series_status"
    " WHERE instrument = :i AND timeframe = :tf"
)
SET_STATUS = text(
    "INSERT INTO series_status (instrument, timeframe, status, last_candle_time, delayed_since,"
    " last_checked_at) VALUES (:i, :tf, :status, :last, :since, :checked)"
    " ON CONFLICT (instrument, timeframe) DO UPDATE SET status = EXCLUDED.status,"
    " last_candle_time = EXCLUDED.last_candle_time, delayed_since = EXCLUDED.delayed_since,"
    " last_checked_at = EXCLUDED.last_checked_at"
)
FIND_GAP = text(
    "SELECT id, gap_to FROM data_gaps WHERE instrument = :i AND timeframe = :tf"
    " AND gap_from = :gf AND filled_at IS NULL"
)
INSERT_GAP = text(
    "INSERT INTO data_gaps (instrument, timeframe, gap_from, gap_to, detected_at)"
    " VALUES (:i, :tf, :gf, :gt, :now)"
)
WIDEN_GAP = text("UPDATE data_gaps SET gap_to = :gt WHERE id = :id AND gap_to < :gt")
UNFILLED = text(
    "SELECT gap_from, gap_to FROM data_gaps WHERE instrument = :i AND timeframe = :tf"
    " AND filled_at IS NULL"
    " AND (CAST(:since AS timestamptz) IS NULL OR detected_at >= :since) ORDER BY gap_from"
)
FILL_GAP = text(
    "UPDATE data_gaps SET filled_at = :now WHERE instrument = :i AND timeframe = :tf"
    " AND gap_from = :gf AND filled_at IS NULL"
)


class SqlCandleStore:
    """CandleStore over one open connection (the caller owns the transaction)."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def last_open_time(self, instrument: str, timeframe: str) -> datetime | None:
        """Open time of the newest stored candle."""
        value = self._conn.execute(LAST_OPEN, {"i": instrument, "tf": timeframe}).scalar()
        return value if isinstance(value, datetime) else None

    def open_times(self, instrument: str, timeframe: str, since: datetime) -> list[datetime]:
        """Open times of stored candles from ``since``, ascending."""
        rows = self._conn.execute(OPEN_TIMES, {"i": instrument, "tf": timeframe, "since": since})
        return [row[0] for row in rows]

    def load(self, instrument: str, timeframe: str, since: datetime | None) -> list[StoredCandle]:
        """Stored candles from ``since`` (all when None), ascending."""
        rows = self._conn.execute(LOAD, {"i": instrument, "tf": timeframe, "since": since})
        return [StoredCandle(**row._mapping) for row in rows]

    def add(self, rows: Sequence[StoredCandle]) -> int:
        """Insert new candles; return how many were inserted."""
        if not rows:
            return 0
        result = self._conn.execute(INSERT_CANDLE, [row.as_row() for row in rows])
        return max(result.rowcount, 0)

    def get_status(self, instrument: str, timeframe: str) -> SeriesStatus | None:
        """The series_status row."""
        row = self._conn.execute(GET_STATUS, {"i": instrument, "tf": timeframe}).first()
        if row is None:
            return None
        return SeriesStatus(row[0], row[1], row[2], row[3])

    def set_status(self, instrument: str, timeframe: str, status: SeriesStatus) -> None:
        """Upsert the series_status row (a row missing from the seed is created)."""
        self._conn.execute(
            SET_STATUS,
            {
                "i": instrument,
                "tf": timeframe,
                "status": status.status,
                "last": status.last_candle_time,
                "since": status.delayed_since,
                "checked": status.checked_at,
            },
        )

    def record_gap(
        self, instrument: str, timeframe: str, gap_from: datetime, gap_to: datetime, now: datetime
    ) -> None:
        """Record a gap unless an unfilled one with the same start exists (then widen it)."""
        params = {"i": instrument, "tf": timeframe, "gf": gap_from}
        found = self._conn.execute(FIND_GAP, params).first()
        if found is None:
            self._conn.execute(INSERT_GAP, {**params, "gt": gap_to, "now": now})
        else:
            self._conn.execute(WIDEN_GAP, {"id": found[0], "gt": gap_to})

    def unfilled_gaps(
        self, instrument: str, timeframe: str, detected_since: datetime | None = None
    ) -> list[tuple[datetime, datetime]]:
        """Unfilled gaps, optionally only those detected since a time."""
        rows = self._conn.execute(
            UNFILLED, {"i": instrument, "tf": timeframe, "since": detected_since}
        )
        return [(row[0], row[1]) for row in rows]

    def fill_gap(self, instrument: str, timeframe: str, gap_from: datetime, now: datetime) -> None:
        """Mark a gap filled."""
        self._conn.execute(FILL_GAP, {"i": instrument, "tf": timeframe, "gf": gap_from, "now": now})
