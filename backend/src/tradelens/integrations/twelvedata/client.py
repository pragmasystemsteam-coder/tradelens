"""Twelve Data REST adapter implementing the market_data candle port (CR-004, FR-DATA-01).

Calls ``GET /time_series`` with ``timezone=UTC``, ``order=ASC`` and ``dp`` = the instrument
price scale, so prices convert to integers exactly. The API key is sent in the
``Authorization: apikey ...`` header, never in a URL, and never appears in logs or errors.
Twelve Data has no completion flag and includes the forming bar; the market_data module
drops it (``candles.complete_bars``).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import httpx

from tradelens.integrations.twelvedata.rate_limiter import CreditLimiter
from tradelens.modules.market_data.candles import PriceFormatError, parse_price
from tradelens.modules.market_data.ports import ProviderError, RateLimitedError, RawBar

BASE_URL = "https://api.twelvedata.com"
INTERVALS = {"5m": "5min", "15m": "15min", "1h": "1h"}
MAX_OUTPUTSIZE = 5000
TIMEOUT_SECONDS = 15.0
HTTP_TOO_MANY = 429
HTTP_OK_MAX = 299
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
DATE_ONLY_LENGTH = 10
MESSAGE_LIMIT = 200
SOURCE = "twelvedata"

log = logging.getLogger("tradelens.integrations.twelvedata")


def _parse_time(text: str) -> datetime:
    fmt = "%Y-%m-%d" if len(text) == DATE_ONLY_LENGTH else TIME_FORMAT
    return datetime.strptime(text, fmt).replace(tzinfo=UTC)


def parse_time_series(doc: Mapping[str, Any], price_scale: int) -> list[RawBar]:
    """Convert a ``/time_series`` body (requested with ``timezone=UTC``) into bars.

    Args:
        doc: Parsed JSON body with ``status == "ok"``.
        price_scale: Decimal places of the instrument.

    Returns:
        Bars in the order of ``values``.

    Raises:
        ProviderError: If a value is missing or malformed.
    """
    try:
        return [
            RawBar(
                _parse_time(str(v["datetime"])),
                parse_price(str(v["open"]), price_scale),
                parse_price(str(v["high"]), price_scale),
                parse_price(str(v["low"]), price_scale),
                parse_price(str(v["close"]), price_scale),
            )
            for v in doc.get("values", [])
        ]
    except (KeyError, TypeError, ValueError, PriceFormatError) as exc:
        raise ProviderError(f"twelvedata: malformed time_series value ({exc})") from None


class TwelveDataProvider:
    """Candle provider backed by the Twelve Data REST API."""

    name = SOURCE

    def __init__(
        self,
        api_key: str,
        symbols: Mapping[str, str],
        price_scales: Mapping[str, int],
        limiter: CreditLimiter,
        http: httpx.Client | None = None,
        base_url: str = BASE_URL,
    ) -> None:
        if not api_key.strip():
            raise ValueError("TWELVEDATA_API_KEY is empty")
        self._key = api_key
        self._symbols = dict(symbols)
        self._scales = dict(price_scales)
        self._limiter = limiter
        self._http = http or httpx.Client(base_url=base_url, timeout=TIMEOUT_SECONDS)

    def source_for(self, instrument: str) -> str:
        """Value of ``candles.source`` for bars from this provider."""
        return SOURCE

    def _get(self, path: str, params: Mapping[str, str]) -> dict[str, Any]:
        self._limiter.acquire(1)
        try:
            response = self._http.get(
                path, params=params, headers={"Authorization": f"apikey {self._key}"}
            )
        except httpx.HTTPError as exc:
            # str(exc) can carry request details; report only the error type.
            raise ProviderError(f"twelvedata {path}: {type(exc).__name__}") from None
        try:
            body = response.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            raise ProviderError(f"twelvedata {path}: HTTP {response.status_code}, no JSON body")
        # Defence in depth: never let the key reach an error message or a log line.
        message = str(body.get("message", "")).replace(self._key, "***")[:MESSAGE_LIMIT]
        if response.status_code == HTTP_TOO_MANY or body.get("code") == HTTP_TOO_MANY:
            log.warning("twelvedata refused a call: credit limit", extra={"path": path})
            raise RateLimitedError(f"twelvedata {path}: {message or 'credit limit reached'}")
        if response.status_code > HTTP_OK_MAX or body.get("status") != "ok":
            raise ProviderError(f"twelvedata {path}: HTTP {response.status_code} {message}")
        return body

    def fetch(
        self,
        instrument: str,
        timeframe: str,
        *,
        count: int,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[RawBar]:
        """Return up to ``count`` bars (ascending, forming bar included); 1 credit per call.

        Raises:
            ValueError: For an unsupported timeframe (a programming error).
            ProviderError: On any API or payload failure, or an instrument without a symbol.
        """
        if timeframe not in INTERVALS:
            raise ValueError(f"twelvedata adapter fetches {sorted(INTERVALS)}, not {timeframe!r}")
        if instrument not in self._symbols or instrument not in self._scales:
            raise ProviderError(f"twelvedata: no symbol or price scale for {instrument!r}")
        params = {
            "symbol": self._symbols[instrument],
            "interval": INTERVALS[timeframe],
            "outputsize": str(max(1, min(count, MAX_OUTPUTSIZE))),
            "timezone": "UTC",
            "order": "ASC",
            "dp": str(self._scales[instrument]),
        }
        if start is not None:
            params["start_date"] = start.astimezone(UTC).strftime(TIME_FORMAT)
        if end is not None:
            params["end_date"] = end.astimezone(UTC).strftime(TIME_FORMAT)
        bars = parse_time_series(self._get("/time_series", params), self._scales[instrument])
        return [
            b
            for b in bars
            if (start is None or b.open_time >= start) and (end is None or b.open_time <= end)
        ]

    def search_symbol(self, symbol: str) -> list[dict[str, Any]]:
        """Return Twelve Data ``/symbol_search`` matches for ``symbol`` (1 credit)."""
        body = self._get("/symbol_search", {"symbol": symbol, "outputsize": "10"})
        data = body.get("data", [])
        return [item for item in data if isinstance(item, dict)]
