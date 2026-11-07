"""Candle-provider port (FR-DATA-01, CR-004).

Implemented by ``tradelens.integrations.twelvedata`` (development, CR-004), the OANDA adapter
(later) and ``tradelens.integrations.fakes``. The market_data module depends only on this
protocol; the worker wires the concrete provider (ADR-0001 section 4).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol


class ProviderError(RuntimeError):
    """The provider could not deliver candles (network, HTTP or payload error)."""


class RateLimitedError(ProviderError):
    """The provider refused the call because a credit or rate limit was reached."""


class BudgetExhaustedError(ProviderError):
    """The client-side daily credit budget is spent; no call was made."""


def _require_int(name: str, value: object) -> None:
    if type(value) is not int:
        raise ValueError(f"{name} must be an int, got {type(value).__name__}")


@dataclass(frozen=True, slots=True)
class RawBar:
    """One provider bar: UTC open time and mid OHLC in smallest price units (AD-12).

    A provider may return the bar that is still forming; ``candles.complete_bars`` removes it.
    """

    open_time: datetime
    o: int
    h: int
    l: int  # noqa: E741 - OHLC naming from the design
    c: int

    def __post_init__(self) -> None:
        offset = self.open_time.utcoffset()
        if offset is None or offset != timedelta(0):
            raise ValueError("open_time must be a timezone-aware UTC datetime")
        for name in ("o", "h", "l", "c"):
            _require_int(name, getattr(self, name))
        if self.h < max(self.o, self.c, self.l) or self.l > min(self.o, self.c, self.h):
            raise ValueError(f"inconsistent OHLC: o={self.o} h={self.h} l={self.l} c={self.c}")


class CandleProvider(Protocol):
    """Source of candles for one or more instruments."""

    name: str

    def source_for(self, instrument: str) -> str:
        """Value stored in ``candles.source`` for bars of ``instrument``."""
        ...

    def fetch(
        self,
        instrument: str,
        timeframe: str,
        *,
        count: int,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[RawBar]:
        """Return up to ``count`` bars in ascending open time.

        Args:
            instrument: Instrument code, e.g. ``EUR_USD``.
            timeframe: ``5m``, ``15m`` or ``1h`` (higher timeframes are built locally).
            count: Maximum number of bars.
            start: Earliest open time wanted (inclusive), or None for the latest bars.
            end: Latest open time wanted (inclusive), or None.

        Returns:
            Bars, possibly including the one still forming.

        Raises:
            ProviderError: On any failure; ``RateLimitedError`` / ``BudgetExhaustedError``
                when a limit stops the call.
        """
        ...
