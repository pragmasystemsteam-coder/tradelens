"""Fake/recorded providers so all 55 series work offline, and provider selection (CR-004)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tradelens.integrations.fakes.recorded import RecordedProvider
from tradelens.integrations.fakes.synthetic import SyntheticProvider
from tradelens.integrations.providers import RoutingProvider, build_candle_provider
from tradelens.integrations.twelvedata.client import TwelveDataProvider
from tradelens.modules.market_data.aggregate import aggregate
from tradelens.modules.market_data.candles import to_stored
from tradelens.modules.market_data.public import load_instrument_specs

REPO = Path(__file__).resolve().parents[4]
FIX = REPO / "backend" / "tests" / "fixtures" / "twelvedata"
NOW = datetime(2026, 11, 10, 15, 2, tzinfo=UTC)  # Tuesday


@pytest.fixture(scope="module")
def specs():
    return load_instrument_specs(REPO / "config")


def test_symbol_map_complete_and_unique(specs):
    symbols = [s.twelvedata_symbol for s in specs]
    assert len(specs) == 11
    assert all(symbols)
    assert len(set(symbols)) == 11
    by_code = {s.code: s.twelvedata_symbol for s in specs}
    assert by_code["EUR_USD"] == "EUR/USD"
    assert by_code["XAU_USD"] == "XAU/USD"
    assert by_code["XAG_USD"] == "XAG/USD"


def test_synthetic_deterministic_and_valid_ohlc(specs):
    p1 = SyntheticProvider(specs, clock=lambda: NOW)
    p2 = SyntheticProvider(specs, clock=lambda: NOW)
    for spec in specs:
        a = p1.fetch(spec.code, "5m", count=50)
        assert a == p2.fetch(spec.code, "5m", count=50)
        assert len(a) == 50
        assert all(b.l <= min(b.o, b.c) and b.h >= max(b.o, b.c) and b.l > 0 for b in a)
        assert a[-1].open_time == datetime(2026, 11, 10, 15, 0, tzinfo=UTC)  # forming bar included


def test_synthetic_skips_closed_market(specs):
    sat = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
    bars = SyntheticProvider(specs, clock=lambda: sat).fetch("EUR_USD", "1h", count=5)
    assert all(b.open_time < datetime(2026, 11, 6, 22, 0, tzinfo=UTC) for b in bars)


def test_synthetic_15m_equals_aggregated_5m(specs):
    p = SyntheticProvider(specs, clock=lambda: NOW)
    fx = next(s for s in specs if s.code == "EUR_USD").calendar
    five = [to_stored(b, "EUR_USD", "5m", "fake") for b in p.fetch("EUR_USD", "5m", count=24)]
    fifteen = p.fetch("EUR_USD", "15m", count=8)
    built = aggregate(fx, "5m", "15m", five, now=NOW)
    by_time = {b.open_time: b for b in fifteen}
    assert built
    for c in built:
        raw = by_time[c.open_time]
        assert (raw.o, raw.h, raw.l, raw.c) == (c.o, c.h, c.l, c.c)


def test_synthetic_start_and_end(specs):
    p = SyntheticProvider(specs, clock=lambda: NOW)
    start = datetime(2026, 11, 10, 14, 0, tzinfo=UTC)
    end = datetime(2026, 11, 10, 14, 30, tzinfo=UTC)
    bars = p.fetch("EUR_USD", "5m", count=100, start=start, end=end)
    assert [b.open_time for b in bars] == [start + timedelta(minutes=5 * i) for i in range(7)]


def test_recorded_provider_replays_fixture(specs):
    p = RecordedProvider(FIX, {"EUR_USD": ("time_series_eurusd_5min.json", 5)})
    bars = p.fetch("EUR_USD", "5m", count=2)
    assert [b.c for b in bars] == [107255, 107251]
    assert bars[-1].open_time == datetime(2026, 11, 6, 14, 25, tzinfo=UTC)
    assert p.fetch("GBP_USD", "5m", count=2) == []


def test_routing_live_subset(specs):
    calls = []

    class Spy:
        def __init__(self, name):
            self.name = name

        def source_for(self, instrument):
            return self.name

        def fetch(self, instrument, timeframe, *, count, start=None, end=None):
            calls.append((self.name, instrument))
            return []

    r = RoutingProvider(Spy("twelvedata"), Spy("fake"), frozenset({"EUR_USD"}))
    r.fetch("EUR_USD", "5m", count=1)
    r.fetch("GBP_USD", "5m", count=1)
    assert calls == [("twelvedata", "EUR_USD"), ("fake", "GBP_USD")]
    assert r.source_for("EUR_USD") == "twelvedata"
    assert r.source_for("GBP_USD") == "fake"


def test_factory_fake_without_key(specs):
    p = build_candle_provider({"MARKET_DATA_PROVIDER": "fake"}, specs, clock=lambda: NOW)
    assert isinstance(p, SyntheticProvider)


def test_factory_twelvedata_requires_key(specs):
    with pytest.raises(ValueError, match="TWELVEDATA_API_KEY"):
        build_candle_provider({"MARKET_DATA_PROVIDER": "twelvedata"}, specs, clock=lambda: NOW)


def test_factory_twelvedata_routes_live_subset(specs):
    env = {"MARKET_DATA_PROVIDER": "twelvedata", "TWELVEDATA_API_KEY": "x" * 20}
    p = build_candle_provider(env, specs, clock=lambda: NOW)
    assert isinstance(p, RoutingProvider)
    assert isinstance(p.live, TwelveDataProvider)
    assert p.live_instruments == frozenset({"EUR_USD", "XAU_USD"})
    env["TWELVEDATA_LIVE_INSTRUMENTS"] = "EUR_USD"
    assert build_candle_provider(env, specs, clock=lambda: NOW).live_instruments == {"EUR_USD"}


def test_factory_rejects_unknown_provider_and_live_instrument(specs):
    with pytest.raises(ValueError):
        build_candle_provider({"MARKET_DATA_PROVIDER": "nope"}, specs, clock=lambda: NOW)
    env = {
        "MARKET_DATA_PROVIDER": "twelvedata",
        "TWELVEDATA_API_KEY": "x" * 20,
        "TWELVEDATA_LIVE_INSTRUMENTS": "EUR_USD,FOO_BAR",
    }
    with pytest.raises(ValueError, match="FOO_BAR"):
        build_candle_provider(env, specs, clock=lambda: NOW)


def test_factory_all_keyword_and_production_needs_all(specs):
    env = {
        "MARKET_DATA_PROVIDER": "twelvedata",
        "TWELVEDATA_API_KEY": "x" * 20,
        "TWELVEDATA_LIVE_INSTRUMENTS": "all",
    }
    assert len(build_candle_provider(env, specs, clock=lambda: NOW).live_instruments) == 11
    env.update(APP_ENV="production", TWELVEDATA_LIVE_INSTRUMENTS="EUR_USD,XAU_USD")
    with pytest.raises(ValueError, match="production"):
        build_candle_provider(env, specs, clock=lambda: NOW)
