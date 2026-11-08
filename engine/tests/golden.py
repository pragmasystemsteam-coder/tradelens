"""Golden file ``data/synthetic_2000.json``: 2,000 synthetic 5m candles and the engine output.

The candles are stored, so the file pins the input as well as the output. The output is
``run_multi`` over 5m and the 15m, 1H, 4H and 1D candles built from them (17:00 New York).

Regenerate only after a reviewed rule change (and say so in the changelog):
    .venv/Scripts/python.exe engine/tests/golden.py --write
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from builders import aggregate, impulsive  # noqa: E402
from conftest import R1_CONSTANTS, R1_USER  # noqa: E402

from tradelens_engine.codec import encode  # noqa: E402
from tradelens_engine.multi import run_multi  # noqa: E402
from tradelens_engine.series import _candle_in, _candle_out  # noqa: E402
from tradelens_engine.settings import Settings  # noqa: E402

GOLDEN = HERE / "data" / "synthetic_2000.json"
INSTRUMENT = "EUR_USD"
RULE_VERSION = "r1.0"
DERIVED = ("15m", "1h", "4h", "1d")


def settings() -> Settings:
    """The official r1.0 settings."""
    return Settings.from_json({"user": dict(R1_USER), "constants": R1_CONSTANTS})


def series_from(five: list) -> dict:
    """5m candles plus the timeframes built from them."""
    return {"5m": five} | {tf: aggregate(five, tf) for tf in DERIVED}


def output(series: dict) -> dict:
    """Engine output per timeframe as plain JSON."""
    cfg = settings()
    result = run_multi(series, cfg, instrument=INSTRUMENT, rule_version=RULE_VERSION)
    return {
        tf: {
            "events": [e.to_json() for e in r.events],
            "zones": [z.to_json() for z in r.zones],
            "zone_transitions": [list(encode(t)) for t in r.zone_transitions],
            "level_changes": [c.to_json() for c in r.level_changes],
            "setup_candidates": [encode(s) for s in r.setup_candidates],
            "final_state": r.state.to_json(),
        }
        for tf, r in sorted(result.items())
    }


def build() -> dict:
    """The whole golden document."""
    five = impulsive(2000)
    return {
        "_comment": "TradeLens golden file (DD 7.3). Regenerate: engine/tests/golden.py --write",
        "instrument": INSTRUMENT,
        "rule_version": RULE_VERSION,
        "settings_hash": settings().hash(RULE_VERSION),
        "candles_5m": [_candle_out(c) for c in five],
        "output": output(series_from(five)),
    }


def load() -> dict:
    """The committed golden document."""
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def stored_candles() -> list:
    """The 2,000 stored 5m candles."""
    return [_candle_in(v) for v in load()["candles_5m"]]


def dumps(doc: dict) -> str:
    """Canonical text: sorted keys, one compact JSON value per top-level output list item."""
    return json.dumps(doc, sort_keys=True, separators=(",", ":")) + "\n"


if __name__ == "__main__":
    if "--write" not in sys.argv:
        sys.exit("usage: golden.py --write")
    GOLDEN.parent.mkdir(exist_ok=True)
    GOLDEN.write_text(dumps(build()), encoding="utf-8", newline="\n")
