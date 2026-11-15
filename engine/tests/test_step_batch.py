"""``step_batch``: the worker's close batch, from saved states (DD 3.5, task 1.9; NFR-07)."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from builders import aggregate, impulsive

from tradelens_engine.multi import run_multi, step_batch
from tradelens_engine.series import SeriesState
from tradelens_engine.settings import Settings
from tradelens_engine.step import OutOfOrderCandle
from tradelens_engine.types import Candle

KW = {"instrument": "EUR_USD", "rule_version": "r1.0"}


@pytest.fixture
def cfg(settings_obj):
    return Settings.from_json(settings_obj(internal_pivot=2, external_pivot=8))


def multi_series(n=1200):
    five = impulsive(n)
    return {tf: aggregate(five, tf) for tf in ("15m", "1h", "4h", "1d")} | {"5m": five}


def test_close_batch_highest_tf_first(cfg):
    # 17:00 New York on a Wednesday closes a 5m, 15m, 1h, 4h and 1d candle at once.
    close = datetime(2026, 11, 11, 22, 0, tzinfo=UTC)
    minutes = {"5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}
    batch = {
        tf: [Candle(close - timedelta(minutes=m), close, 100, 110, 90, 105, 105, 105)]
        for tf, m in minutes.items()
    }
    result = step_batch({}, batch, cfg, **KW)
    assert [tf for tf, _ in result.steps] == ["1d", "4h", "1h", "15m", "5m"]
    assert all(t == close for _, t in result.steps)


def test_step_batch_in_chunks_equals_run_multi(cfg):
    series = multi_series()
    whole = run_multi(series, cfg, **KW)
    cut = series["5m"][700].close_time
    states: dict[str, SeriesState] = {}
    outputs: dict[str, list] = {tf: [] for tf in series}
    first = {tf: [c for c in cs if c.close_time <= cut] for tf, cs in series.items()}
    second = {tf: [c for c in cs if c.close_time > cut] for tf, cs in series.items()}
    for part in (first, second):
        # JSON round-trip between batches, as the worker does through series_state.
        states = {tf: SeriesState.from_json(json.loads(json.dumps(s.to_json())))
                  for tf, s in states.items()}  # fmt: skip
        res = step_batch(states, part, cfg, **KW)
        states = dict(res.states)
        for tf, outs in res.outputs.items():
            outputs[tf].extend(outs)
    for tf, r in whole.items():
        assert [e for o in outputs[tf] for e in o.events] == list(r.events), tf
        assert [s for o in outputs[tf] for s in o.setup_candidates] == list(r.setup_candidates)
        assert states[tf].to_json() == r.state.to_json()


def test_step_batch_rejects_candle_not_after_state(cfg):
    series = multi_series(200)
    first = step_batch({}, {"5m": series["5m"][:50]}, cfg, **KW)
    with pytest.raises(OutOfOrderCandle):
        step_batch(dict(first.states), {"5m": series["5m"][49:60]}, cfg, **KW)


def test_step_batch_empty_batch_keeps_states(cfg):
    first = step_batch({}, {"5m": multi_series(100)["5m"]}, cfg, **KW)
    again = step_batch(dict(first.states), {"5m": []}, cfg, **KW)
    assert again.steps == ()
    assert again.states["5m"] is first.states["5m"]
