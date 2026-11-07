"""Choose the candle provider from the environment (CR-004). Used by the worker and the CLI.

``MARKET_DATA_PROVIDER``:

* ``fake`` - synthetic bars for every series (no network, no key).
* ``twelvedata`` - Twelve Data for ``TWELVEDATA_LIVE_INSTRUMENTS`` (default EUR_USD and
  XAU_USD, as CR-004 allows on the FREE plan; ``all`` = every instrument) and synthetic bars
  for every other instrument. In production the list must be ``all``: synthetic prices are
  never allowed next to real ones for paying users.
  Needs ``TWELVEDATA_API_KEY``. Limits: ``TWELVEDATA_CREDITS_PER_MINUTE`` (8) and
  ``TWELVEDATA_CREDITS_PER_DAY`` (800).

OANDA becomes a third choice once its account is verified.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime

import httpx

from tradelens.integrations.fakes.synthetic import SyntheticProvider
from tradelens.integrations.twelvedata.client import BASE_URL, TIMEOUT_SECONDS, TwelveDataProvider
from tradelens.integrations.twelvedata.rate_limiter import (
    FREE_PER_DAY,
    FREE_PER_MINUTE,
    CreditLimiter,
)
from tradelens.modules.market_data.ports import CandleProvider, RawBar
from tradelens.modules.market_data.public import InstrumentSpec

DEFAULT_LIVE = "EUR_USD,XAU_USD"
ALL = "all"
PROVIDERS = ("fake", "twelvedata")


class RoutingProvider:
    """Send live instruments to one provider and every other instrument to a fallback."""

    name = "routing"

    def __init__(
        self, live: CandleProvider, fallback: CandleProvider, live_instruments: frozenset[str]
    ) -> None:
        self.live = live
        self.fallback = fallback
        self.live_instruments = live_instruments

    def _pick(self, instrument: str) -> CandleProvider:
        return self.live if instrument in self.live_instruments else self.fallback

    def source_for(self, instrument: str) -> str:
        """Value of ``candles.source`` for ``instrument``."""
        return self._pick(instrument).source_for(instrument)

    def fetch(
        self,
        instrument: str,
        timeframe: str,
        *,
        count: int,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[RawBar]:
        """Delegate to the live provider or the fallback."""
        return self._pick(instrument).fetch(
            instrument, timeframe, count=count, start=start, end=end
        )


def _int(env: Mapping[str, str], key: str, default: int) -> int:
    raw = env.get(key, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"{key} must be an integer") from None


def build_candle_provider(
    env: Mapping[str, str],
    specs: Sequence[InstrumentSpec],
    clock: Callable[[], datetime],
    *,
    http: httpx.Client | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> CandleProvider:
    """Build the provider selected by ``MARKET_DATA_PROVIDER`` (default ``fake``).

    Raises:
        ValueError: On an unknown provider, a missing key or an unknown live instrument.
    """
    choice = env.get("MARKET_DATA_PROVIDER", "").strip() or "fake"
    synthetic = SyntheticProvider(specs, clock)
    if choice == "fake":
        return synthetic
    if choice != "twelvedata":
        raise ValueError(f"MARKET_DATA_PROVIDER must be one of {PROVIDERS}, not {choice!r}")
    key = env.get("TWELVEDATA_API_KEY", "").strip()
    if not key:
        raise ValueError("TWELVEDATA_API_KEY is required when MARKET_DATA_PROVIDER=twelvedata")
    known = frozenset(s.code for s in specs)
    raw_live = env.get("TWELVEDATA_LIVE_INSTRUMENTS", "").strip() or DEFAULT_LIVE
    if raw_live == ALL:
        live = known
    else:
        live = frozenset(code.strip() for code in raw_live.split(",") if code.strip())
    if env.get("APP_ENV") == "production" and live != known:
        raise ValueError("TWELVEDATA_LIVE_INSTRUMENTS must be 'all' in production (no fake data)")
    unknown = sorted(live - known)
    if unknown:
        raise ValueError(f"TWELVEDATA_LIVE_INSTRUMENTS has unknown instruments: {unknown}")
    limiter = CreditLimiter(
        per_minute=_int(env, "TWELVEDATA_CREDITS_PER_MINUTE", FREE_PER_MINUTE),
        per_day=_int(env, "TWELVEDATA_CREDITS_PER_DAY", FREE_PER_DAY),
        clock=clock,
        sleep=sleep,
    )
    client = http or httpx.Client(
        base_url=env.get("TWELVEDATA_BASE_URL", "").strip() or BASE_URL, timeout=TIMEOUT_SECONDS
    )
    td = TwelveDataProvider(
        api_key=key,
        symbols={s.code: s.twelvedata_symbol for s in specs if s.twelvedata_symbol},
        price_scales={s.code: s.price_scale for s in specs},
        limiter=limiter,
        http=client,
    )
    return RoutingProvider(td, synthetic, live)
