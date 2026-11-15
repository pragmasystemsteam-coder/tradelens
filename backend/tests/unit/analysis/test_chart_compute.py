"""On-demand chart compute and provisional swings (DD 4.2; task 2.6; FR-CUST-04, FR-SCAN-03)."""

import json
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tradelens.integrations.fakes.synthetic import SyntheticProvider
from tradelens.modules.analysis.public import (
    compute_overlays,
    official_settings,
    provisional_swings,
)
from tradelens.modules.market_data.candles import to_stored
from tradelens.modules.market_data.public import load_instrument_specs
from tradelens_engine.series import SeriesState
from tradelens_engine.types import Candle

REPO = Path(__file__).resolve().parents[4]
END = datetime(2026, 11, 13, 21, 0, tzinfo=UTC)


def rule_doc():
    return json.loads((REPO / "config" / "rules" / "r1.0.json").read_text(encoding="utf-8"))


def stored(count, tf="1h"):
    provider = SyntheticProvider(load_instrument_specs(REPO / "config"), lambda: END)
    bars = provider.fetch("EUR_USD", tf, count=count, end=END - timedelta(hours=1))
    return [to_stored(b, "EUR_USD", tf, "synthetic") for b in bars]


def test_preset_compute_3000_candles_under_5s():
    rows = stored(3000)
    assert len(rows) == 3000
    doc = rule_doc()
    preset = next(p for p in doc["presets"] if p["code"] == "swing")
    cfg = official_settings({**doc, "user": preset["user"]})
    started = time.perf_counter()
    out = compute_overlays(rows, "EUR_USD", "1h", cfg, "r1.0")
    elapsed = time.perf_counter() - started
    assert elapsed < 5, f"preset chart over 3,000 candles took {elapsed:.2f} s"
    assert out.events and out.zones and out.liquidity
    assert out.state is not None and out.state.bar_index == 3000


def bar(i, h, low):
    t0 = datetime(2026, 11, 2, tzinfo=UTC) + timedelta(hours=i)
    return Candle(t0, t0 + timedelta(hours=1), low, h, low, h, h, h)


def test_provisional_swings_follow_left_and_right_tests():
    cfg = official_settings(rule_doc())  # internal pivot 3 on 1h, external 10
    highs = [100, 101, 102, 103, 110, 104, 103]  # bar 4: left test passes, 2 right bars so far
    window = tuple(bar(i, h, h - 50) for i, h in enumerate(highs))
    state = replace(SeriesState(), window=window, bar_index=len(window))
    swings = provisional_swings(state, cfg, "1h")
    hi = [s for s in swings if s["type"] == "swing_high" and s["structure"] == "internal"]
    assert [s["price"] for s in hi] == [110]
    assert hi[0]["origin_time"] == "2026-11-02T04:00:00Z"
    assert all("id" not in s for s in swings)  # never stored, never an event
    # A higher high to the right fails the right test.
    window2 = (*window, bar(7, 111, 60))
    swings2 = provisional_swings(replace(state, window=window2), cfg, "1h")
    assert 110 not in [s["price"] for s in swings2 if s["type"] == "swing_high"]
