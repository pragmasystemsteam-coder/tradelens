"""Candles: price parsing, the completed-candle rule and stored rows (FR-DATA-01/02, AD-04).

Twelve Data has no "complete" flag (CR-004), so a bar counts as complete only once its close
time (open + timeframe) has passed. Prices become integers in smallest units without floats.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any

from tradelens.modules.market_data.ports import RawBar

TIMEFRAME_MINUTES: dict[str, int] = {"5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}
PRICE_TEXT = re.compile(r"^(\d+)(?:\.(\d+))?$")


class PriceFormatError(ValueError):
    """A provider price string that cannot be converted exactly."""


def timeframe_delta(timeframe: str) -> timedelta:
    """Length of one candle of ``timeframe``."""
    try:
        return timedelta(minutes=TIMEFRAME_MINUTES[timeframe])
    except KeyError:
        raise ValueError(f"unknown timeframe {timeframe!r}") from None


def parse_price(text: str, price_scale: int) -> int:
    """Convert a decimal price string to smallest units, exactly (no float, no rounding).

    Args:
        text: Price as the provider sends it, e.g. ``"1.07215"``.
        price_scale: Decimal places of the instrument (``instruments.price_scale``).

    Returns:
        ``price * 10**price_scale`` as an int.

    Raises:
        PriceFormatError: If ``text`` is not a plain non-negative decimal, or has non-zero
            digits beyond ``price_scale``.
    """
    match = PRICE_TEXT.match(text)
    if match is None:
        raise PriceFormatError(f"not a price: {text!r}")
    whole, frac = match.group(1), match.group(2) or ""
    if len(frac) > price_scale:
        if frac[price_scale:].strip("0"):
            raise PriceFormatError(f"{text!r} has more than {price_scale} decimals")
        frac = frac[:price_scale]
    return int(whole + frac.ljust(price_scale, "0"))


def normalise_bars(bars: Iterable[RawBar]) -> list[RawBar]:
    """Sort by open time and keep one bar per open time (the last one seen wins)."""
    by_time = {bar.open_time: bar for bar in bars}
    return [by_time[t] for t in sorted(by_time)]


def complete_bars(bars: Iterable[RawBar], timeframe: str, now: datetime) -> list[RawBar]:
    """Drop every bar whose close time is after ``now`` (the forming bar is never used).

    Args:
        bars: Provider bars.
        timeframe: Their timeframe.
        now: Current UTC time (from the injected clock).

    Returns:
        Complete bars only, sorted and de-duplicated.
    """
    step = timeframe_delta(timeframe)
    return [bar for bar in normalise_bars(bars) if bar.open_time + step <= now]


@dataclass(frozen=True, slots=True)
class StoredCandle:
    """A row of the ``candles`` table (DD 2.4). Bid/ask equal mid when the source has no spread."""

    instrument: str
    timeframe: str
    open_time: datetime
    o: int
    h: int
    l: int  # noqa: E741
    c: int
    bid_o: int
    bid_h: int
    bid_l: int
    bid_c: int
    ask_o: int
    ask_h: int
    ask_l: int
    ask_c: int
    source: str
    tick_volume: int = 0

    @property
    def close_time(self) -> datetime:
        """Open time plus the timeframe (no trading day spans a DST switch)."""
        return self.open_time + timeframe_delta(self.timeframe)

    def as_row(self) -> dict[str, Any]:
        """Column values for an INSERT."""
        return asdict(self)


def to_stored(bar: RawBar, instrument: str, timeframe: str, source: str) -> StoredCandle:
    """Build a stored candle from a mid-only bar (CR-004 D2-2: bid = ask = mid, spread 0)."""
    o, h, l, c = bar.o, bar.h, bar.l, bar.c  # noqa: E741
    return StoredCandle(
        instrument, timeframe, bar.open_time, o, h, l, c, o, h, l, c, o, h, l, c, source
    )
