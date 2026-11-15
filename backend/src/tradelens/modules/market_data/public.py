"""Public interface of market_data for other modules and the CLI (ADR-0001 section 4)."""

from tradelens.modules.market_data.calendar import Calendar
from tradelens.modules.market_data.candle_store import (
    SqlCandleStore,
    latest_closes,
    load_last_candles,
)
from tradelens.modules.market_data.candles import StoredCandle
from tradelens.modules.market_data.ingest import IngestService, InstrumentReport, SeriesStatus
from tradelens.modules.market_data.repository import instrument_rows, series_status_rows
from tradelens.modules.market_data.service import (
    TIMEFRAMES,
    InstrumentSpec,
    ReferenceDataError,
    ReferenceRows,
    build_reference_rows,
    load_instrument_specs,
    save_reference_rows,
)

__all__ = [
    "TIMEFRAMES",
    "Calendar",
    "IngestService",
    "InstrumentReport",
    "InstrumentSpec",
    "ReferenceDataError",
    "ReferenceRows",
    "SeriesStatus",
    "SqlCandleStore",
    "StoredCandle",
    "build_reference_rows",
    "instrument_rows",
    "latest_closes",
    "load_instrument_specs",
    "load_last_candles",
    "save_reference_rows",
    "series_status_rows",
]
