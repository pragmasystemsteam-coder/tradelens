"""Deterministic synthetic candles for every instrument (FR-DATA-07, CR-004 development).

With the Twelve Data FREE plan only a small live subset is affordable, so every other series
runs from these bars. A bar depends only on (instrument, open time): repeated calls, restarts
and different processes see identical data. Prices are whole numbers in smallest units; 15m and
1h bars are exact aggregates of the 5m bars, like real provider data.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta

from tradelens.modules.market_data.calendar import bucket_open, is_expected
from tradelens.modules.market_data.candles import timeframe_delta
from tradelens.modules.market_data.ports import RawBar
from tradelens.modules.market_data.public import InstrumentSpec

SOURCE = "fake"
TIMEFRAMES = ("5m", "15m", "1h")
FIVE = timedelta(minutes=5)
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
# Base prices as decimal strings (no floats); rough real levels so charts look familiar.
BASE_PRICES = {
    "EUR_USD": "1.08", "GBP_USD": "1.27", "USD_JPY": "150", "USD_CHF": "0.88",
    "AUD_USD": "0.66", "USD_CAD": "1.36", "NZD_USD": "0.60", "XAU_USD": "2650",
    "XAG_USD": "31", "WTICO_USD": "70", "BCO_USD": "74",
}  # fmt: skip
DEFAULT_BASE = "100"
# (period in 5m bars, amplitude in pips): a day, a week and a short cycle.
WAVES = ((288, 40), (2016, 150), (61, 12))
NOISE_PIPS = 6
WICK_PIPS = 4
SCAN_LIMIT_FACTOR = 4  # weekends and breaks: scan at most this many slots per bar wanted
SCAN_LIMIT_EXTRA = 4000


def _units(text: str, price_scale: int) -> int:
    whole, _, frac = text.partition(".")
    return int(whole + frac.ljust(price_scale, "0"))


def _triangle(x: int, period: int, amplitude: int) -> int:
    r = x % period
    v = r if r < period // 2 else period - r
    return (4 * amplitude * v) // period - amplitude


def _pip(spec: InstrumentSpec) -> int:
    return int(10 ** (spec.price_scale - spec.pip_scale))


def _noise(code: str, x: int, salt: str) -> int:
    digest = hashlib.sha256(f"{code}|{x}|{salt}".encode()).digest()
    return int.from_bytes(digest[:4], "big")


class SyntheticProvider:
    """Candle provider that computes bars instead of fetching them."""

    name = SOURCE

    def __init__(self, specs: Sequence[InstrumentSpec], clock: Callable[[], datetime]) -> None:
        self._specs = {s.code: s for s in specs}
        self._clock = clock

    def source_for(self, instrument: str) -> str:
        """Value of ``candles.source`` for bars from this provider."""
        return SOURCE

    def _price(self, spec: InstrumentSpec, x: int) -> int:
        pip = _pip(spec)
        base = _units(BASE_PRICES.get(spec.code, DEFAULT_BASE), spec.price_scale)
        wave = sum(_triangle(x, period, amp) for period, amp in WAVES)
        noise = _noise(spec.code, x, "p") % (2 * NOISE_PIPS + 1) - NOISE_PIPS
        return base + (wave + noise) * pip

    def _bar5(self, spec: InstrumentSpec, t: datetime) -> RawBar:
        x = (t - EPOCH) // FIVE
        pip = _pip(spec)
        o, c = self._price(spec, x), self._price(spec, x + 1)
        up = (_noise(spec.code, x, "h") % (WICK_PIPS + 1)) * pip
        down = (_noise(spec.code, x, "l") % (WICK_PIPS + 1)) * pip
        return RawBar(t, o, max(o, c) + up, min(o, c) - down, c)

    def _bar(self, spec: InstrumentSpec, timeframe: str, t: datetime) -> RawBar | None:
        steps = timeframe_delta(timeframe) // FIVE
        subs = [
            self._bar5(spec, t + k * FIVE)
            for k in range(steps)
            if is_expected(spec.calendar, "5m", t + k * FIVE)
        ]
        if not subs:
            return None
        return RawBar(t, subs[0].o, max(b.h for b in subs), min(b.l for b in subs), subs[-1].c)

    def fetch(
        self,
        instrument: str,
        timeframe: str,
        *,
        count: int,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[RawBar]:
        """Return up to ``count`` bars ending at the forming bar (or ``end``), ascending."""
        if timeframe not in TIMEFRAMES:
            raise ValueError(f"synthetic provider serves {TIMEFRAMES}, not {timeframe!r}")
        spec = self._specs.get(instrument)
        if spec is None:
            raise ValueError(f"unknown instrument {instrument!r}")
        step = timeframe_delta(timeframe)
        latest = bucket_open(timeframe, self._clock())
        t = latest if end is None else min(latest, bucket_open(timeframe, end))
        out: list[RawBar] = []
        for _ in range(count * SCAN_LIMIT_FACTOR + SCAN_LIMIT_EXTRA):
            if len(out) >= count or (start is not None and t < start):
                break
            if is_expected(spec.calendar, timeframe, t):
                bar = self._bar(spec, timeframe, t)
                if bar is not None:
                    out.append(bar)
            t -= step
        out.reverse()
        return out
