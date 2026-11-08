"""Higher-timeframe context and run_multi (DD 3.5; FR-MTF-02, NFR-07)."""

import json

import pytest
from builders import aggregate, impulsive
from scenario import BASE, candles

from tradelens_engine.context import build_context
from tradelens_engine.multi import TF_ORDER, run_multi
from tradelens_engine.run import run
from tradelens_engine.series import SeriesState
from tradelens_engine.settings import Settings
from tradelens_engine.step import step

KW = {"instrument": "EUR_USD", "rule_version": "r1.0"}


@pytest.fixture
def cfg(settings_obj):
    return Settings.from_json(settings_obj(internal_pivot=2, external_pivot=8))


def multi_series(n=1500):
    five = impulsive(n)
    return {tf: aggregate(five, tf) for tf in ("15m", "1h", "4h", "1d")} | {"5m": five}


def test_build_context_profiles_and_not_ready(cfg):
    four = run(candles(BASE, "4h"), cfg, timeframe="4h", **KW).state
    day = run(candles(BASE[:10], "1d"), cfg, timeframe="1d", **KW).state
    one = run(candles(BASE, "1h"), cfg, timeframe="1h", **KW).state
    ctx = build_context({"4h": four, "1d": day, "1h": one}, "intraday")
    assert [t.timeframe for t in ctx.contexts] == ["1d", "4h"]
    d, f = ctx.contexts
    assert d.ready is False and d.trend == "neutral" and d.zones == ()  # 10 candles < 14
    assert f.ready is True and f.trend == "bull" and f.atr_k == four.atr.atr_k
    assert f.as_of == four.last_close_time
    assert {z.kind for z in f.zones} == {"ob", "fvg"}
    assert all(z.state in ("confirmed", "touched", "mitigated_50", "filled") for z in f.zones)
    assert [t.timeframe for t in build_context({"1h": one}, "scalping").contexts] == ["1h"]
    swing = build_context({}, "swing").contexts
    assert [(t.timeframe, t.ready) for t in swing] == [("1d", False)]


def test_run_multi_single_series_equals_run(cfg):
    series = multi_series(600)
    multi = run_multi(series, cfg, **KW)
    for tf in ("5m", "1d"):
        alone = run(series[tf], cfg, timeframe=tf, **KW)
        assert multi[tf].events == alone.events
        assert multi[tf].zone_transitions == alone.zone_transitions


def test_run_multi_equals_live_order(cfg):
    """Live: at each close, step the closing timeframes highest first from saved JSON states."""
    series = multi_series(1500)
    multi = run_multi(series, cfg, **KW)
    states = {tf: SeriesState() for tf in series}
    outputs = {tf: [] for tf in series}
    closes = sorted({c.close_time for cs in series.values() for c in cs})
    by_close = {tf: {c.close_time: c for c in cs} for tf, cs in series.items()}
    from tradelens_engine.context import PROFILE_BY_TF

    for t in closes:
        for tf in TF_ORDER:
            candle = by_close.get(tf, {}).get(t)
            if candle is None:
                continue
            saved = {k: SeriesState.from_json(json.loads(json.dumps(v.to_json())))
                     for k, v in states.items()}  # fmt: skip
            htf = build_context(saved, PROFILE_BY_TF[tf]) if tf in PROFILE_BY_TF else None
            states[tf], out = step(saved[tf], candle, cfg, timeframe=tf, htf=htf, **KW)
            outputs[tf].append(out)
    for tf in series:
        assert tuple(e for o in outputs[tf] for e in o.events) == multi[tf].events, tf
        got = tuple(s for o in outputs[tf] for s in o.setup_candidates)
        assert got == multi[tf].setup_candidates, tf
    assert sum(len(r.setup_candidates) for r in multi.values()) > 0
    with_ctx = [s for s in multi["1h"].setup_candidates if s.context is not None]
    assert with_ctx and all([t.timeframe for t in s.context.contexts] == ["1d", "4h"]
                            for s in with_ctx)  # fmt: skip


def test_context_never_sees_a_later_htf_close(cfg):
    series = multi_series(1500)
    multi = run_multi(series, cfg, **KW)
    for s in multi["1h"].setup_candidates:
        for t in s.context.contexts:
            assert t.as_of is None or t.as_of <= s.confirm_time


def test_run_multi_rejects_unsorted_series(cfg):
    from tradelens_engine.step import OutOfOrderCandle

    c = candles(BASE, "1h")
    with pytest.raises(OutOfOrderCandle):
        run_multi({"1h": [c[1], c[0]]}, cfg, **KW)
    with pytest.raises(ValueError, match="unknown timeframe"):
        run_multi({"2h": c}, cfg, **KW)
