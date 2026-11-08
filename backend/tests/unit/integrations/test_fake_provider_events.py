"""The fake provider gives the same engine events as the recording (FR-DATA-07; DD 8.1 task 1.8).

``time_series_eurusd_5min_week.json`` is a Twelve Data ``/time_series`` body (UTC, ascending)
recorded from the synthetic provider for EUR/USD 5m, Monday 9 to Thursday 12 November 2026.
``engine_events_eurusd_5min_week.json`` holds the reviewed engine events for it. The test
replays the recording through ``RecordedProvider``, runs the engine, and checks that the
events equal both the recorded expectation and a run over the synthetic provider's bars.

Regenerate both files only after a reviewed rule change:
    .venv/Scripts/python.exe backend/tests/unit/integrations/test_fake_provider_events.py
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from tradelens.integrations.fakes.recorded import RecordedProvider
from tradelens.integrations.fakes.synthetic import SyntheticProvider
from tradelens.modules.market_data.ports import RawBar
from tradelens.modules.market_data.public import load_instrument_specs
from tradelens_engine.run import run
from tradelens_engine.settings import Settings
from tradelens_engine.types import Candle

REPO = Path(__file__).resolve().parents[4]
FIX = REPO / "backend" / "tests" / "fixtures" / "twelvedata"
RECORDING = "time_series_eurusd_5min_week.json"
EXPECTED = FIX / "engine_events_eurusd_5min_week.json"
START = datetime(2026, 11, 9, 0, 0, tzinfo=UTC)
END = datetime(2026, 11, 12, 11, 15, tzinfo=UTC)
NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
COUNT = 1000
SCALE = 5


def settings() -> Settings:
    doc = json.loads((REPO / "config" / "rules" / "r1.0.json").read_text(encoding="utf-8"))
    return Settings.from_json({"user": doc["user"], "constants": doc["constants"]})


def to_engine(bar: RawBar) -> Candle:
    """Mid-only bar -> engine candle (CR-004 D2-2: bid = ask = mid)."""
    return Candle.of(bar.open_time, "5m", bar.o, bar.h, bar.l, bar.c, bid_c=bar.c, ask_c=bar.c)


def events(bars: list[RawBar]) -> list[dict]:
    result = run([to_engine(b) for b in bars], settings(), instrument="EUR_USD",
                 timeframe="5m", rule_version="r1.0")  # fmt: skip
    return [e.to_json() for e in result.events]


def synthetic_bars() -> list[RawBar]:
    specs = load_instrument_specs(REPO / "config")
    return SyntheticProvider(specs, clock=lambda: NOW).fetch(
        "EUR_USD", "5m", count=COUNT, start=START, end=END
    )


def test_fake_provider_same_events_as_recorded():
    recorded = RecordedProvider(FIX, {"EUR_USD": (RECORDING, SCALE)}).fetch(
        "EUR_USD", "5m", count=COUNT
    )
    assert len(recorded) == COUNT
    assert recorded == synthetic_bars()
    got = events(recorded)
    assert got == json.loads(EXPECTED.read_text(encoding="utf-8"))
    assert {e["type"] for e in got} >= {"swing_high", "swing_low", "bos", "breakout", "sweep"}


def _price(units: int) -> str:
    text = str(units).rjust(SCALE + 1, "0")
    return f"{text[:-SCALE]}.{text[-SCALE:]}"


def write_fixtures() -> None:
    """Record the synthetic bars in Twelve Data's format and the engine events they give."""
    bars = synthetic_bars()
    doc = {
        "_comment": "Twelve Data /time_series format (order=ASC, timezone=UTC, dp=5), recorded "
        "from the synthetic provider (FR-DATA-07). Regenerate: see test_fake_provider_events.py",
        "meta": {
            "symbol": "EUR/USD",
            "interval": "5min",
            "currency_base": "Euro",
            "currency_quote": "US Dollar",
            "type": "Physical Currency",
        },
        "values": [
            {
                "datetime": b.open_time.strftime("%Y-%m-%d %H:%M:%S"),
                "open": _price(b.o),
                "high": _price(b.h),
                "low": _price(b.l),
                "close": _price(b.c),
            }
            for b in bars
        ],
        "status": "ok",
    }
    (FIX / RECORDING).write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8", newline="\n")
    EXPECTED.write_text(json.dumps(events(bars), indent=1) + "\n", encoding="utf-8", newline="\n")
    sys.stdout.write(f"wrote {RECORDING} ({len(bars)} bars) and {EXPECTED.name}\n")


if __name__ == "__main__":
    sys.exit(write_fixtures())
