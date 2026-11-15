"""Golden events from two weeks of real Twelve Data history (DD 8.1 task 1.10; DD 7.3).

``engine/tests/golden/td_{eurusd,xauusd}_5m_2w.json`` are /time_series bodies recorded on
10 Nov 2026 (scripts/record_golden.py, 2 credits): 5m bars from Mon 26 Oct to Fri 6 Nov 2026,
which includes the US DST change on 1 Nov (17:00 New York moves from 21:00 to 22:00 UTC).

The bars go through the production path: calendar filter (weekend and metal-break bars are
dropped), stored candles (mid only, bid = ask, CR-004), 15m and 1H from 5m, 4H and 1D from 1H
on the 17:00 New York boundary, then ``run_multi`` with the official r1.0 settings.

``*.expected.json`` holds the reviewed events. ``test_golden_events_pass_rule_review`` re-checks
every event against its candles, so the expectation is not just "whatever the code printed".
Regenerate only after a reviewed rule change:
    .venv/Scripts/python.exe backend/tests/unit/analysis/test_golden_events.py --write
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tradelens.integrations.twelvedata.client import parse_time_series
from tradelens.modules.analysis.process import to_engine
from tradelens.modules.analysis.service import official_settings
from tradelens.modules.market_data.aggregate import aggregate
from tradelens.modules.market_data.calendar import is_expected
from tradelens.modules.market_data.candles import complete_bars, to_stored
from tradelens.modules.market_data.public import load_instrument_specs
from tradelens_engine.multi import run_multi

REPO = Path(__file__).resolve().parents[4]
GOLDEN = REPO / "engine" / "tests" / "golden"
CASES = {"EUR_USD": "td_eurusd_5m_2w", "XAU_USD": "td_xauusd_5m_2w"}
NOW = datetime(2026, 11, 7, 0, 0, tzinfo=UTC)  # after the last recorded bar
RULE_VERSION = "r1.0"
DERIVED = (("5m", "15m"), ("5m", "1h"), ("1h", "4h"), ("1h", "1d"))


def settings():
    doc = json.loads((REPO / "config" / "rules" / "r1.0.json").read_text(encoding="utf-8"))
    return official_settings(doc)


def series(instrument):
    """Engine candles per timeframe, built exactly as the worker builds them."""
    spec = next(s for s in load_instrument_specs(REPO / "config") if s.code == instrument)
    doc = json.loads((GOLDEN / f"{CASES[instrument]}.json").read_text(encoding="utf-8"))
    bars = complete_bars(parse_time_series(doc, spec.price_scale), "5m", NOW)
    stored = {"5m": [to_stored(b, instrument, "5m", "twelvedata") for b in bars
                     if is_expected(spec.calendar, "5m", b.open_time)]}  # fmt: skip
    for source, target in DERIVED:
        stored[target] = aggregate(spec.calendar, source, target, stored[source], NOW)
    return {tf: [to_engine(c) for c in rows] for tf, rows in stored.items()}, len(bars)


def output(instrument):
    candles, raw = series(instrument)
    result = run_multi(candles, settings(), instrument=instrument, rule_version=RULE_VERSION)
    events = {
        tf: [[e.id, e.type, e.structure, e.direction, e.level, e.origin_time.isoformat(),
              e.confirm_time.isoformat()] for e in r.events]
        for tf, r in sorted(result.items())
    }  # fmt: skip
    return {
        "instrument": instrument,
        "rule_version": RULE_VERSION,
        "settings_hash": settings().hash(RULE_VERSION),
        "raw_bars": raw,
        "candles": {tf: len(cs) for tf, cs in sorted(candles.items())},
        "event_counts": {
            tf: dict(sorted(Counter(e[1] for e in ev).items())) for tf, ev in events.items()
        },
        "events": events,
        "zones": {tf: [z.id for z in r.zones] for tf, r in sorted(result.items())},
        "setup_candidates": {
            tf: [[s.id, s.direction, list(s.patterns)] for s in r.setup_candidates]
            for tf, r in sorted(result.items())
        },
    }


def expected(instrument):
    path = GOLDEN / f"{CASES[instrument]}.expected.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("instrument", sorted(CASES))
def test_golden_events(instrument):
    assert output(instrument) == expected(instrument)


@pytest.mark.parametrize("instrument", sorted(CASES))
def test_golden_covers_every_timeframe_and_rule(instrument):
    exp = expected(instrument)
    assert set(exp["candles"]) == {"5m", "15m", "1h", "4h", "1d"}
    assert exp["candles"]["5m"] < exp["raw_bars"]  # weekend bars from the provider were dropped
    counts = Counter()
    for by_type in exp["event_counts"].values():
        counts.update(by_type)
    assert {"swing_high", "swing_low", "bos", "choch", "sweep", "breakout",
            "displacement"} <= set(counts)  # fmt: skip
    assert sum(len(z) for z in exp["zones"].values()) > 0
    assert sum(len(s) for s in exp["setup_candidates"].values()) > 0


@pytest.mark.parametrize("instrument", sorted(CASES))
def test_golden_events_pass_rule_review(instrument):
    """Every event agrees with its candles (DD 3.4), independent of the engine code."""
    candles, _ = series(instrument)
    cfg = settings()
    exp = expected(instrument)
    for tf, events in exp["events"].items():
        cs = candles[tf]
        by_close = {c.close_time.isoformat(): c for c in cs}
        index = {c.open_time.isoformat(): i for i, c in enumerate(cs)}
        swings = {(e[2], e[1], e[4], e[5]) for e in events if e[1].startswith("swing")}
        for _id, type_, structure, direction, level, origin, confirm in events:
            c = by_close[confirm]
            if type_.startswith("swing"):
                k = cfg.internal_pivot_for(tf) if structure == "internal" else cfg.external_pivot
                i = index[origin]
                window = cs[max(0, i - k) : i + k + 1]
                pivot = cs[i]
                assert cs[i + k].close_time.isoformat() == confirm, (tf, origin)
                if type_ == "swing_high":
                    assert pivot.h == level == max(x.h for x in window), (tf, origin)
                else:
                    assert pivot.l == level == min(x.l for x in window), (tf, origin)
            elif type_ in ("bos", "choch"):
                assert (c.c > level) if direction == "bull" else (c.c < level), (tf, confirm)
                kind = "swing_high" if direction == "bull" else "swing_low"
                assert (structure, kind, level, origin) in swings, (tf, type_, confirm)
            elif type_ == "breakout":
                assert (c.c > level) if direction == "bull" else (c.c < level), (tf, confirm)
            elif type_ == "sweep":
                if direction == "bull":
                    assert c.l < level < c.c, (tf, confirm)
                else:
                    assert c.c < level < c.h, (tf, confirm)


def test_twelvedata_has_no_bid_ask():
    """CR-004: mid prices only, so measured spreads are 0 and normal_spread stays a placeholder."""
    for name in CASES.values():
        doc = json.loads((GOLDEN / f"{name}.json").read_text(encoding="utf-8"))
        assert all(set(v) == {"datetime", "open", "high", "low", "close"} for v in doc["values"])


def write() -> None:
    for instrument, name in CASES.items():
        path = GOLDEN / f"{name}.expected.json"
        path.write_text(json.dumps(output(instrument), separators=(",", ":")) + "\n",
                        encoding="utf-8")  # fmt: skip


if __name__ == "__main__" and "--write" in sys.argv:
    write()
