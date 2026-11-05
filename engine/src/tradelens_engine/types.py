"""Core value types (Detailed Design 3.1)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, get_args

Timeframe = Literal["5m", "15m", "1h", "4h", "1d"]
Dir = Literal["bull", "bear"]
Side = Literal["buy", "sell"]

TIMEFRAMES: tuple[Timeframe, ...] = get_args(Timeframe)
TIMEFRAME_MINUTES: dict[str, int] = {"5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}


def require_int(name: str, value: object) -> int:
    """Return ``value`` if it is a plain int; bools and floats are rejected (DD-5).

    Args:
        name: Field name used in the error message.
        value: Value to check.

    Returns:
        The int, unchanged.

    Raises:
        ValueError: If ``value`` is not exactly an int.
    """
    if type(value) is not int:
        raise ValueError(f"{name} must be an int, got {type(value).__name__}")
    return value


def require_aware(name: str, value: object) -> datetime:
    """Return ``value`` if it is a timezone-aware datetime.

    Args:
        name: Field name used in the error message.
        value: Value to check.

    Returns:
        The datetime, unchanged.

    Raises:
        ValueError: If ``value`` is not an aware datetime.
    """
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")
    return value


def require_utc(name: str, value: object) -> datetime:
    """Return ``value`` if it is an aware datetime with a zero UTC offset.

    Args:
        name: Field name used in the error message.
        value: Value to check.

    Returns:
        The datetime, unchanged.

    Raises:
        ValueError: If ``value`` is naive or not in UTC.
    """
    dt = require_aware(name, value)
    if dt.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be in UTC")
    return dt


@dataclass(frozen=True, slots=True)
class Candle:
    """A complete candle. Prices are mid prices in smallest units (price x 10**price_scale)."""

    open_time: datetime
    close_time: datetime
    o: int
    h: int
    l: int  # noqa: E741 - OHLC naming from the design
    c: int
    bid_c: int
    ask_c: int

    def __post_init__(self) -> None:
        require_utc("open_time", self.open_time)
        require_utc("close_time", self.close_time)
        if self.close_time <= self.open_time:
            raise ValueError("close_time must be after open_time")
        for name in ("o", "h", "l", "c", "bid_c", "ask_c"):
            require_int(name, getattr(self, name))
        if self.h < max(self.o, self.c, self.l) or self.l > min(self.o, self.c, self.h):
            raise ValueError(f"inconsistent OHLC: o={self.o} h={self.h} l={self.l} c={self.c}")
        if self.ask_c < self.bid_c:
            raise ValueError("ask_c must be >= bid_c")

    @classmethod
    def of(
        cls,
        open_time: datetime,
        timeframe: str,
        o: int,
        h: int,
        l: int,  # noqa: E741
        c: int,
        *,
        bid_c: int,
        ask_c: int,
    ) -> Candle:
        """Build a candle whose close is open + timeframe.

        FX and commodity markets are closed when New York changes clocks (Sunday 02:00),
        so a 4h or 1d candle aligned to 17:00 New York never spans a DST switch.
        """
        if timeframe not in TIMEFRAME_MINUTES:
            raise ValueError(f"unknown timeframe {timeframe!r}")
        close_time = open_time + timedelta(minutes=TIMEFRAME_MINUTES[timeframe])
        return cls(open_time, close_time, o, h, l, c, bid_c, ask_c)
