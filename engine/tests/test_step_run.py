"""step() and run() for swings, structure and FVG (DD 3.1, 3.4, 7.2, 7.3; NFR-07, FR-SMC-11)."""

import json

import pytest
from builders import WORKED, series, synthetic

from tradelens_engine.run import run
from tradelens_engine.series import SeriesState
from tradelens_engine.settings import Settings
from tradelens_engine.step import OutOfOrderCandle, step

STRUCTURE = ("swing_high", "swing_low", "bos", "choch")
KW = {"instrument": "EUR_USD", "timeframe": "5m", "rule_version": "r1.0"}


@pytest.fixture
def cfg(settings_obj):
    return Settings.from_json(settings_obj())


@pytest.fixture
def cfg2(settings_obj):
    return Settings.from_json(settings_obj(internal_pivot=2, external_pivot=8))


def test_out_of_order_raises(cfg):
    c = synthetic(3)
    state, _ = step(SeriesState(), c[1], cfg, **KW)
    with pytest.raises(OutOfOrderCandle):
        step(state, c[0], cfg, **KW)
    with pytest.raises(OutOfOrderCandle):
        step(state, c[1], cfg, **KW)  # the same candle twice


def test_worked_example_bull_trend_then_bos(cfg2):
    c = series(WORKED)
    result = run(c, cfg2, **KW)
    got = [
        (e.type, e.structure, e.direction, e.level, e.origin_time, e.confirm_time)
        for e in result.events
        if e.type in STRUCTURE
    ]
    assert got == [
        ("swing_high", "internal", None, 15, c[2].open_time, c[4].close_time),
        ("swing_low", "internal", None, 6, c[4].open_time, c[6].close_time),
        ("swing_high", "internal", None, 17, c[6].open_time, c[8].close_time),
        ("swing_low", "internal", None, 9, c[9].open_time, c[11].close_time),
        ("bos", "internal", "bull", 17, c[6].open_time, c[12].close_time),
    ]
    assert result.state.internal.trend == "bull"
    assert result.state.internal.protected_low.price == 9
    assert [
        (z.kind, z.direction, z.low, z.high, z.origin_time, z.confirm_time) for z in result.zones
    ] == [("fvg", "bull", 15, 16, c[10].open_time, c[12].close_time)]
    zid = result.zones[0].id
    assert result.zone_transitions == (
        (zid, "detected", c[12].close_time),
        (zid, "confirmed", c[12].close_time),
    )


def test_events_carry_ids_and_settings_hash(cfg):
    result = run(synthetic(600), cfg, **KW)
    assert result.events
    h = cfg.hash("r1.0")
    assert all(e.settings_hash == h and e.rule_version == "r1.0" for e in result.events)
    ids = [e.id for e in result.events] + [z.id for z in result.zones]
    assert all(len(i) == 32 and int(i, 16) >= 0 for i in ids)
    assert len(ids) == len(set(ids))
    assert {e.structure for e in result.events if e.type in STRUCTURE} == {"internal", "external"}
    assert {e.structure for e in result.events if e.type not in STRUCTURE} <= {None}
    assert {"bos", "choch"} & {e.type for e in result.events}


def test_every_event_is_confirmed_by_the_candle_that_emitted_it(cfg):
    state = SeriesState()
    for candle in synthetic(500):
        state, out = step(state, candle, cfg, **KW)
        assert all(e.confirm_time == candle.close_time for e in out.events)
        assert all(e.origin_time <= e.confirm_time for e in out.events)
        assert all(z.confirm_time == candle.close_time for z in out.new_zones)


def test_step_vs_run_parity_with_json_round_trip(cfg):
    candles = synthetic(2000)
    full = run(candles, cfg, **KW)
    state, events, zones, transitions = SeriesState(), [], [], []
    for candle in candles:
        state = SeriesState.from_json(json.loads(json.dumps(state.to_json())))
        state, out = step(state, candle, cfg, **KW)
        events += out.events
        zones += out.new_zones
        transitions += out.zone_transitions
    assert tuple(events) == full.events
    assert tuple(zones) == full.zones
    assert tuple(transitions) == full.zone_transitions
    assert state.to_json() == full.state.to_json()


def test_state_window_and_history_are_bounded(cfg):
    state = run(synthetic(800), cfg, **KW).state
    assert len(state.window) == 64
    assert len(state.recent_fvgs) <= 6
    assert len(state.internal.highs) <= 30
    assert state.bar_index == 800


def test_truncation_no_look_ahead(cfg):
    candles = synthetic(300)
    full = run(candles, cfg, **KW)
    for n in range(1, len(candles) + 1):
        cut = candles[n - 1].close_time
        part = run(candles[:n], cfg, **KW)
        assert part.events == tuple(e for e in full.events if e.confirm_time <= cut), n
        assert part.zones == tuple(z for z in full.zones if z.confirm_time <= cut), n


def test_internal_and_external_events_on_the_same_bar_have_distinct_ids(settings_obj):
    cfg = Settings.from_json(settings_obj(internal_pivot=None, external_pivot=10))
    cfg_same = Settings.from_json(settings_obj(internal_pivot=5, external_pivot=8))
    for c in (cfg, cfg_same):
        result = run(synthetic(1200), c, **KW)
        ids = [e.id for e in result.events]
        assert len(ids) == len(set(ids))


def test_htf_uses_pivot_5(cfg):
    from builders import bar as mk

    highs = [10, 11, 12, 13, 14, 50, 14, 13, 12, 11, 10]
    candles = [mk(i, h, h - 5, tf="4h") for i, h in enumerate(highs, start=1)]
    # 4h candles must not overlap: rebuild with 4-hour spacing.
    from datetime import timedelta

    from tradelens_engine.types import Candle

    candles = [Candle.of(candles[0].open_time + timedelta(hours=4 * i), "4h", c.o, c.h, c.l, c.c,
                         bid_c=c.c, ask_c=c.c) for i, c in enumerate(candles)]  # fmt: skip
    events = run(candles, cfg, instrument="EUR_USD", timeframe="4h", rule_version="r1.0").events
    assert [(e.type, e.level) for e in events if e.structure == "internal"] == [("swing_high", 50)]
    events = run(
        candles[:10], cfg, instrument="EUR_USD", timeframe="4h", rule_version="r1.0"
    ).events
    assert [
        e for e in events if e.type in STRUCTURE
    ] == []  # with pivot 5 the swing needs five candles on the right


def test_a_swing_is_never_broken_by_the_candle_that_confirms_it(cfg):
    """Review: trend start + break on one candle. Confirming a swing needs H[k] >= every later
    high up to t (mirror for lows), so the confirming close cannot be beyond it."""
    state = SeriesState()
    for candle in synthetic(1500):
        state, out = step(state, candle, cfg, **KW)
        confirmed = {(e.structure, e.level, e.origin_time) for e in out.events if "swing" in e.type}
        broken = {
            (e.structure, e.level, e.origin_time) for e in out.events if "swing" not in e.type
        }
        assert not confirmed & broken


def test_state_has_a_version_and_old_state_is_refused(cfg):
    from tradelens_engine.series import STATE_VERSION, StateVersionError

    state = run(synthetic(50), cfg, **KW).state.to_json()
    assert state["v"] == STATE_VERSION
    old = {k: v for k, v in state.items() if k not in ("v", "levels")}  # a Day 2 row
    with pytest.raises(StateVersionError):
        SeriesState.from_json(old)
    broken = {**state, "levels": [{"id": "x"}]}
    with pytest.raises(ValueError, match="missing"):
        SeriesState.from_json(broken)
