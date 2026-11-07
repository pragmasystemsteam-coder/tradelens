"""Twelve Data adapter against recorded-format responses; never a live call (CR-004)."""

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from tradelens.integrations.twelvedata.client import TwelveDataProvider, parse_time_series
from tradelens.integrations.twelvedata.rate_limiter import CreditLimiter
from tradelens.modules.market_data.ports import ProviderError, RateLimitedError

FIX = Path(__file__).resolve().parents[2] / "fixtures" / "twelvedata"
KEY = "td-test-key-not-real"


def load(name):
    return json.loads((FIX / name).read_text())


def provider(handler, limiter=None):
    http = httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://api.twelvedata.com"
    )
    return TwelveDataProvider(
        api_key=KEY,
        symbols={"EUR_USD": "EUR/USD", "XAU_USD": "XAU/USD"},
        price_scales={"EUR_USD": 5, "XAU_USD": 3},
        limiter=limiter or CreditLimiter(per_minute=8, per_day=800),
        http=http,
    )


def test_parse_time_series_values_to_int_bars():
    bars = parse_time_series(load("time_series_eurusd_5min.json"), 5)
    assert len(bars) == 6
    assert bars[0].open_time == datetime(2026, 11, 6, 14, 0, tzinfo=UTC)
    assert (bars[0].o, bars[0].h, bars[0].l, bars[0].c) == (107200, 107231, 107188, 107215)
    assert bars[3].c == 107210


def test_time_series_recorded_response_parsed():
    seen = {}

    def handler(request):
        seen["request"] = request
        return httpx.Response(200, json=load("time_series_eurusd_5min.json"))

    bars = provider(handler).fetch("EUR_USD", "5m", count=6)
    req = seen["request"]
    assert req.url.path == "/time_series"
    params = dict(req.url.params)
    assert params["symbol"] == "EUR/USD"
    assert params["interval"] == "5min"
    assert params["timezone"] == "UTC"
    assert params["order"] == "ASC"
    assert params["dp"] == "5"
    assert params["outputsize"] == "6"
    assert "apikey" not in params  # the key travels in a header, never in a URL that may be logged
    assert req.headers["Authorization"] == f"apikey {KEY}"
    assert [b.c for b in bars][:2] == [107215, 107236]


def test_fetch_passes_start_and_end_in_utc():
    seen = {}

    def handler(request):
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json=load("time_series_eurusd_5min.json"))

    start = datetime(2026, 11, 6, 14, 5, tzinfo=UTC)
    end = datetime(2026, 11, 6, 14, 15, tzinfo=UTC)
    bars = provider(handler).fetch("EUR_USD", "5m", count=100, start=start, end=end)
    assert seen["params"]["start_date"] == "2026-11-06 14:05:00"
    assert seen["params"]["end_date"] == "2026-11-06 14:15:00"
    assert [b.open_time.minute for b in bars] == [5, 10, 15]


def test_credit_error_body_raises():
    body = load("error_credits_minute.json")
    with pytest.raises(RateLimitedError):
        provider(lambda r: httpx.Response(200, json=body)).fetch("EUR_USD", "5m", count=3)
    with pytest.raises(RateLimitedError):
        provider(lambda r: httpx.Response(429, json=body)).fetch("EUR_USD", "5m", count=3)


def test_bad_symbol_body_raises_provider_error():
    body = load("error_bad_symbol.json")
    with pytest.raises(ProviderError, match="not found"):
        provider(lambda r: httpx.Response(200, json=body)).fetch("EUR_USD", "5m", count=3)


def test_http_error_raises_provider_error_without_key():
    def handler(request):
        raise httpx.ConnectError("boom", request=request)

    with pytest.raises(ProviderError) as info:
        provider(handler).fetch("EUR_USD", "5m", count=3)
    assert KEY not in str(info.value)


def test_server_error_and_bad_json_raise_provider_error():
    with pytest.raises(ProviderError):
        provider(lambda r: httpx.Response(503, text="down")).fetch("EUR_USD", "5m", count=3)
    with pytest.raises(ProviderError):
        provider(lambda r: httpx.Response(200, text="not json")).fetch("EUR_USD", "5m", count=3)


def test_bad_price_in_payload_raises_provider_error():
    doc = load("time_series_eurusd_5min.json")
    doc["values"][0]["close"] = "1.072159"
    with pytest.raises(ProviderError):
        provider(lambda r: httpx.Response(200, json=doc)).fetch("EUR_USD", "5m", count=3)


def test_unsupported_timeframe_and_instrument_rejected():
    p = provider(lambda r: httpx.Response(200, json={}))
    with pytest.raises(ValueError):
        p.fetch("EUR_USD", "4h", count=3)
    with pytest.raises(ProviderError):
        p.fetch("GBP_USD", "5m", count=3)


def test_key_echoed_in_error_message_is_redacted():
    body = {"code": 401, "message": f"apikey {KEY} is invalid", "status": "error"}
    with pytest.raises(ProviderError) as info:
        provider(lambda r: httpx.Response(401, json=body)).fetch("EUR_USD", "5m", count=3)
    assert KEY not in str(info.value)
    assert "***" in str(info.value)


def test_each_call_spends_one_credit():
    limiter = CreditLimiter(per_minute=8, per_day=800)
    p = provider(lambda r: httpx.Response(200, json=load("time_series_eurusd_5min.json")), limiter)
    p.fetch("EUR_USD", "5m", count=3)
    p.fetch("EUR_USD", "5m", count=3)
    assert limiter.remaining_today == 798


def test_search_symbol_parses_recorded_response():
    p = provider(lambda r: httpx.Response(200, json=load("symbol_search_eurusd.json")))
    found = p.search_symbol("EUR/USD")
    assert found[0]["symbol"] == "EUR/USD"
    assert found[0]["instrument_type"] == "Physical Currency"
