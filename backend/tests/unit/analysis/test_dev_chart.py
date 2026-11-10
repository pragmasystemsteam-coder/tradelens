"""Development-only chart page (DD 8.1 task 1.10): payload, routes and production guard."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from tradelens.app.main import create_app
from tradelens.core.config import AppConfig
from tradelens.integrations.fakes.synthetic import SyntheticProvider
from tradelens.modules.analysis.chart_data import chart_payload
from tradelens.modules.analysis.router import get_chart_source
from tradelens.modules.analysis.service import official_settings
from tradelens.modules.market_data.candles import to_stored
from tradelens.modules.market_data.public import load_instrument_specs

REPO = Path(__file__).resolve().parents[4]
NOW = datetime(2026, 11, 11, 22, 0, tzinfo=UTC)


def cfg():
    doc = json.loads((REPO / "config" / "rules" / "r1.0.json").read_text(encoding="utf-8"))
    return official_settings(doc)


def stored(tf="1h", count=400):
    specs = load_instrument_specs(REPO / "config")
    bars = SyntheticProvider(specs, lambda: NOW).fetch("EUR_USD", tf, count=count)
    return [
        to_stored(b, "EUR_USD", tf, "fake") for b in bars if b.open_time + timedelta(hours=1) <= NOW
    ]


def test_chart_payload_has_candles_and_every_overlay():
    p = chart_payload(stored(), "EUR_USD", "1h", cfg(), "r1.0", price_scale=5, show=300)
    assert p["instrument"] == "EUR_USD" and p["timeframe"] == "1h" and p["price_scale"] == 5
    assert len(p["candles"]) == 300
    first = p["candles"][0]
    assert set(first) == {"time", "open", "high", "low", "close"}
    assert all(isinstance(first[k], int) for k in ("open", "high", "low", "close"))  # no floats
    kinds = {m["kind"] for m in p["markers"]}
    assert {"swing_high", "swing_low"} <= kinds
    assert kinds & {"bos", "choch"}
    assert {z["kind"] for z in p["zones"]} <= {"ob", "fvg"} and p["zones"]
    assert p["levels"]
    start = p["candles"][0]["time"]
    assert all(m["time"] >= start for m in p["markers"])  # only the shown window
    z = p["zones"][0]
    assert z["low"] <= z["high"] and z["start"] <= z["end"]


def test_chart_payload_is_deterministic():
    a = chart_payload(stored(), "EUR_USD", "1h", cfg(), "r1.0", price_scale=5, show=200)
    b = chart_payload(stored(), "EUR_USD", "1h", cfg(), "r1.0", price_scale=5, show=200)
    assert a == b


class FakeSource:
    rule_version = "r1.0"

    def __init__(self):
        self.settings = cfg()

    def candles(self, instrument, timeframe):
        return stored(timeframe)

    def price_scale(self, instrument):
        return 5


def dev_client(env="development"):
    app = create_app(AppConfig.from_env({"APP_ENV": env}))
    app.dependency_overrides[get_chart_source] = lambda: FakeSource()
    return TestClient(app)


def test_dev_chart_page_and_data_in_development():
    client = dev_client()
    page = client.get("/dev/chart")
    assert page.status_code == 200
    assert "lightweight-charts" in page.text and "/dev/chart/data" in page.text
    data = client.get("/dev/chart/data", params={"instrument": "EUR_USD", "timeframe": "1h"})
    assert data.status_code == 200
    assert data.json()["candles"]


def test_dev_chart_rejects_unknown_timeframe():
    client = dev_client()
    bad = client.get("/dev/chart/data", params={"instrument": "EUR_USD", "timeframe": "2h"})
    assert bad.status_code == 422


def test_dev_chart_absent_in_production():
    client = dev_client(env="production")
    assert client.get("/dev/chart").status_code == 404
    assert client.get("/dev/chart/data", params={"instrument": "EUR_USD"}).status_code == 404
