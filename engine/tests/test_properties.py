"""No look-ahead and determinism properties (DD 7.3; NFR-07, FR-SMC-11, FR-MTF-02).

Run on the 2,000-candle golden series (``data/synthetic_2000.json``) and its 15m/1H/4H/1D
aggregates: step vs run with a JSON round trip after every candle, truncation for every n,
a randomised forming 4H candle through ``run_multi``, and two processes with different hash
seeds and time zones.
"""

import hashlib
import json
import os
import random
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from builders import aggregate
from golden import (
    INSTRUMENT,
    RULE_VERSION,
    build,
    dumps,
    load,
    series_from,
    settings,
    stored_candles,
)

from tradelens_engine.codec import encode
from tradelens_engine.multi import run_multi
from tradelens_engine.run import run
from tradelens_engine.series import SeriesState
from tradelens_engine.step import step
from tradelens_engine.types import Candle

TESTS = Path(__file__).resolve().parent
KW = {"instrument": INSTRUMENT, "rule_version": RULE_VERSION}


@pytest.fixture(scope="module")
def cfg():
    return settings()


@pytest.fixture(scope="module")
def five():
    return stored_candles()


def everything(res):
    """All outputs of a result as plain JSON (setups include their HTF context)."""
    return {
        "events": [e.to_json() for e in res.events],
        "zones": [z.to_json() for z in res.zones],
        "transitions": [encode(t) for t in res.zone_transitions],
        "levels": [c.to_json() for c in res.level_changes],
        "setups": [encode(s) for s in res.setup_candidates],
    }


def test_golden_file_matches(five):
    doc = load()
    assert len(doc["candles_5m"]) == 2000
    assert dumps(build()) == dumps(doc), "engine output changed: review, then golden.py --write"


def test_golden_series_covers_every_rule(five):
    out = load()["output"]
    types = {e["type"] for tf in out.values() for e in tf["events"]}
    assert types == {"swing_high", "swing_low", "bos", "choch", "sweep", "breakout", "displacement"}
    assert {z["kind"] for tf in out.values() for z in tf["zones"]} == {"fvg", "ob"}
    states = {t[1] for tf in out.values() for t in tf["zone_transitions"]}
    assert states == {"detected", "confirmed", "touched", "mitigated_50", "filled", "invalidated",
                      "expired"}  # fmt: skip
    reasons = {c["level"]["end_reason"] for tf in out.values() for c in tf["level_changes"]}
    assert {"swept", "breakout", "superseded", "merged"} <= reasons
    kinds = {k for tf in out.values() for c in tf["level_changes"] for k in c["level"]["kinds"]}
    assert {"swing_high", "eqh", "pdh", "asian_high", "london_low", "ny_high"} <= kinds
    assert sum(len(out[tf]["setup_candidates"]) for tf in ("15m", "1h")) > 0


@pytest.mark.parametrize("tf", ["5m", "15m", "1h"])
def test_step_vs_run_with_json_round_trip(cfg, five, tf):
    candles = series_from(five)[tf]
    full = run(candles, cfg, timeframe=tf, **KW)
    state, outs = SeriesState(), []
    for candle in candles:
        state = SeriesState.from_json(json.loads(json.dumps(state.to_json())))
        state, out = step(state, candle, cfg, timeframe=tf, **KW)
        outs.append(out)
    looped = {
        "events": [e.to_json() for o in outs for e in o.events],
        "zones": [z.to_json() for o in outs for z in o.new_zones],
        "transitions": [encode(t) for o in outs for t in o.zone_transitions],
        "levels": [c.to_json() for o in outs for c in o.level_changes],
        "setups": [encode(s) for o in outs for s in o.setup_candidates],
    }
    assert looped == everything(full)
    assert state.to_json() == full.state.to_json()


def known_by(res, cut):
    """Outputs of ``res`` that were knowable at ``cut`` (an OB's 'detected' row is written at
    promotion, so a transition counts from its zone's confirm time)."""
    confirm = {z.id: z.confirm_time for z in res.zones}
    return {
        "events": [e.to_json() for e in res.events if e.confirm_time <= cut],
        "zones": [z.to_json() for z in res.zones if z.confirm_time <= cut],
        "transitions": [
            encode(t) for t in res.zone_transitions if max(t[2], confirm.get(t[0], t[2])) <= cut
        ],
        "levels": [c.to_json() for c in res.level_changes if c.at <= cut],
        "setups": [encode(s) for s in res.setup_candidates if s.confirm_time <= cut],
    }


def test_truncation_every_n_no_look_ahead(cfg, five):
    candles = series_from(five)["15m"][:500]
    full = run(candles, cfg, timeframe="15m", **KW)
    assert full.setup_candidates
    for n in range(1, len(candles) + 1):
        part = run(candles[:n], cfg, timeframe="15m", **KW)
        assert everything(part) == known_by(full, candles[n - 1].close_time), n


def forming(start, rng: random.Random) -> Candle:
    """A random 4H candle opening at ``start`` (the next 4H bucket)."""
    o, a, b = rng.randint(100_000, 120_000), rng.randint(0, 3000), rng.randint(0, 3000)
    c = rng.randint(o - b, o + a)
    return Candle(start, start + timedelta(hours=4), o, o + a, o - b, c, c - 2, c + 2)


def test_forming_htf_candle_changes_no_1h_output(cfg):
    from builders import impulsive

    five = impulsive(3600)
    one, four, day = (aggregate(five, tf) for tf in ("1h", "4h", "1d"))
    full = run_multi({"1h": one, "4h": four, "1d": day}, cfg, **KW)
    assert full["1h"].setup_candidates
    base = everything(full["1h"])
    rng = random.Random(20261108)  # noqa: S311 - test data, not security
    for n in range(1, len(one) + 1):
        cut = one[n - 1].close_time
        closed4 = [c for c in four if c.close_time <= cut]
        closed1d = [c for c in day if c.close_time <= cut]
        start = closed4[-1].close_time if closed4 else four[0].open_time
        noisy = [*closed4, forming(start, rng)]  # its close is after ``cut``: still forming
        part = run_multi({"1h": one[:n], "4h": noisy, "1d": closed1d}, cfg, **KW)
        assert everything(part["1h"]) == known_by(full["1h"], cut), n
    assert base == everything(full["1h"])


SCRIPT = """
import hashlib, json, sys
sys.path.insert(0, sys.argv[1])
from golden import output, series_from, stored_candles
blob = json.dumps(output(series_from(stored_candles())), sort_keys=True)
print(hashlib.sha256(blob.encode()).hexdigest())
"""


def in_process(seed: str, tz: str) -> str:
    env = {**os.environ, "PYTHONHASHSEED": seed, "TZ": tz}
    out = subprocess.run(  # noqa: S603 - fixed argv
        [sys.executable, "-c", SCRIPT, str(TESTS)], capture_output=True, text=True, check=True,
        env=env,
    )  # fmt: skip
    return out.stdout.strip()


def test_two_process_determinism_run_multi():
    a = in_process("1", "UTC")
    b = in_process("987654", "America/Los_Angeles")
    assert a == b and len(a) == 64
    golden = hashlib.sha256(json.dumps(load()["output"], sort_keys=True).encode()).hexdigest()
    assert a == golden
