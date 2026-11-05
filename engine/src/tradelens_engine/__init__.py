"""TradeLens SMC engine: pure, deterministic, integer-only (Detailed Design section 3).

No I/O, wall clock, randomness or floats. Prices are integers in each instrument's
smallest unit; ATR is stored x1000 (``atr_k``); multipliers are in thousandths.
"""

from tradelens_engine.arith import (
    AtrState,
    atr_update,
    body_ratio_ok,
    combined_score,
    ge_atr,
    le_atr,
)
from tradelens_engine.ids import event_id, level_id, make_id, setup_id, zone_id
from tradelens_engine.settings import ALLOWED_VALUES, Settings, SettingsError, settings_hash
from tradelens_engine.timekeys import DEFAULT_SESSIONS, ny_day_key, ny_week_key, sessions_of
from tradelens_engine.types import TIMEFRAME_MINUTES, TIMEFRAMES, Candle, Dir, Side, Timeframe

__all__ = [
    "ALLOWED_VALUES",
    "DEFAULT_SESSIONS",
    "TIMEFRAMES",
    "TIMEFRAME_MINUTES",
    "AtrState",
    "Candle",
    "Dir",
    "Settings",
    "SettingsError",
    "Side",
    "Timeframe",
    "atr_update",
    "body_ratio_ok",
    "combined_score",
    "event_id",
    "ge_atr",
    "le_atr",
    "level_id",
    "make_id",
    "ny_day_key",
    "ny_week_key",
    "sessions_of",
    "settings_hash",
    "setup_id",
    "zone_id",
]
