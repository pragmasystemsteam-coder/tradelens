"""Scoring: Q, C, combined, counter-trend, re-evaluation and explanations (DD 3.6, 3.7; task 2.2).

DD 7.2 row "Scoring": each Q and C factor earned; each factor missed, with reason; missing OB,
liquidity or ATR scores 0 with reason; 60 is high quality, 59 is not; rounding half up.
"""

import dataclasses
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tradelens_engine.context import ContextZone, HigherTfContext, TfContext
from tradelens_engine.events import SeriesKey
from tradelens_engine.scoring import (
    ScoringConfig,
    ScoringConfigError,
    combined,
    explain,
    high_quality,
    reevaluate,
    score_candidate,
    sentences,
)
from tradelens_engine.setups import SetupCandidate

REPO = Path(__file__).resolve().parents[3]
T = datetime(2026, 11, 11, 14, 0, tzinfo=UTC)  # 1H break close, London/New York overlap
H = "h" * 64
ATR = 100_000  # atr_k: ATR = 100 units (10 pips on a 5-decimal pair)
OB, FVG = "o" * 32, "f" * 32


@pytest.fixture
def cfg():
    doc = json.loads((REPO / "config" / "rules" / "r1.0.json").read_text(encoding="utf-8"))
    return ScoringConfig.from_json({"scoring_version": doc["scoring_version"], **doc["weights"]})


def ctx(tf, trend, zones=(), ready=True, atr_k=ATR * 4):
    return TfContext(tf, ready, trend if ready else "neutral", atr_k if ready else None,
                     T - timedelta(hours=1), tuple(zones))  # fmt: skip


def czone(direction, low, high, kind="ob", zid="c" * 32):
    return ContextZone(zid, kind, direction, low, high, "confirmed")


def intraday(day, four):
    return HigherTfContext("intraday", (day, four))


def cand(**kw):
    base = dict(  # noqa: C408 - keyword form mirrors the dataclass
        id="s" * 32, instrument="EUR_USD", timeframe="1h", profile="intraday", direction="bull",
        break_event_id="b" * 32, break_type="bos",
        patterns=("bos", "displacement", "sweep", "fvg", "ob"), sessions=("london", "new_york"),
        spread=10, atr_k=ATR, displacement_event_id="d" * 32, displacement_strong=True,
        sweep_event_id="w" * 32, ob_zone_id=OB, fvg_zone_id=FVG,
        ob_pre_touched=False, invalidation=108_000, opposing_level=108_300,
        origin_time=T - timedelta(hours=3), confirm_time=T, settings_hash=H,
        rule_version="r1.0", zone_low=108_000, zone_high=108_050, break_level=108_100,
        displacement_candles=2, context=intraday(ctx("1d", "bull"), ctx("4h", "bull")),
    )  # fmt: skip
    base.update(kw)
    return SetupCandidate(**base)


def score(cfg, price_scale=5, **kw):
    return score_candidate(cand(**kw), cfg, normal_spread=12, price_scale=price_scale)


def by_code(setup):
    return {f.code: (f.points, f.reason) for f in setup.factors}


def test_every_factor_earned(cfg):
    inside = czone("bull", 107_900, 108_020)
    s = score(cfg, context=intraday(ctx("1d", "bull", [inside]), ctx("4h", "bull")))
    assert by_code(s) == {
        "break": (25, "strong"), "sweep": (20, "sweep_found"), "fvg": (20, "fvg_found"),
        "ob_fresh": (15, "ob_fresh"), "room": (15, "room_ge2"), "spread_session": (5, "ok"),
        "htf_trend": (40, "agree_all"), "htf_zone": (30, "inside"),
        "ltf_confirm": (0, "zone_not_touched"), "no_conflict": (10, "clear"),
    }  # fmt: skip
    assert (s.q, s.c, s.combined) == (100, 80, 92)
    assert s.high_quality
    assert not s.counter_trend
    assert (s.status, s.revision, s.status_time) == ("confirmed", 1, T)
    assert [r.reason for r in s.revisions] == ["created"]


def test_every_factor_missed_with_reason(cfg):
    opposing = czone("bear", 108_060, 108_100)
    s = score(cfg, displacement_strong=False, sweep_event_id=None, fvg_zone_id=None,
              ob_pre_touched=True, opposing_level=108_120, spread=20, sessions=("asian",),
              patterns=("bos", "displacement", "ob"),
              context=intraday(ctx("1d", "bear", [opposing]), ctx("4h", "neutral")))  # fmt: skip
    assert by_code(s) == {
        "break": (15, "minimal"), "sweep": (0, "no_sweep"), "fvg": (0, "no_fvg"),
        "ob_fresh": (0, "ob_pre_touched"), "room": (0, "room_lt1"),
        "spread_session": (0, "wide_spread"), "htf_trend": (0, "none"), "htf_zone": (0, "none"),
        "ltf_confirm": (0, "zone_not_touched"), "no_conflict": (0, "conflict"),
    }  # fmt: skip


def test_partial_points(cfg):
    s = score(cfg, opposing_level=108_050 + 150, sessions=("asian",),
              context=intraday(ctx("1d", "bull"), ctx("4h", "bear")))  # fmt: skip
    f = by_code(s)
    assert f["room"] == (8, "room_ge1")  # 1.5 x ATR
    assert f["spread_session"] == (0, "off_session")
    assert f["htf_trend"] == (20, "agree_one")


def test_missing_ob_liquidity_or_atr_scores_zero_with_reason(cfg):
    f = by_code(score(cfg, ob_zone_id=None, opposing_level=None))
    assert f["ob_fresh"] == (0, "no_ob")
    assert f["room"] == (0, "no_opposing_level")
    assert by_code(score(cfg, atr_k=None))["room"] == (0, "no_atr")
    lost = intraday(ctx("1d", "bull", ready=False), ctx("4h", "bull", ready=False))
    f = by_code(score(cfg, context=lost))
    assert f["htf_trend"] == (0, "not_ready")
    assert f["no_conflict"] == (0, "not_ready")
    assert by_code(score(cfg, context=None))["htf_trend"] == (0, "not_ready")


def test_q_and_c_share_no_factor(cfg):
    s = score(cfg)
    q = {f.code for f in s.factors if f.score == "Q"}
    c = {f.code for f in s.factors if f.score == "C"}
    assert q == {"break", "sweep", "fvg", "ob_fresh", "room", "spread_session"}
    assert c == {"htf_trend", "htf_zone", "ltf_confirm", "no_conflict"}
    assert not q & c
    assert sum(f.max for f in s.factors if f.score == "Q") == 100
    assert sum(f.max for f in s.factors if f.score == "C") == 100
    # A Q input never moves C and a C input never moves Q.
    weak_q = score(cfg, sweep_event_id=None, fvg_zone_id=None)
    assert weak_q.c == s.c
    assert weak_q.q < s.q
    weak_c = score(cfg, context=None)
    assert weak_c.q == s.q
    assert weak_c.c < s.c


def test_counter_trend_badge(cfg):
    # 1H bull setup with 1D and 4H bear: trend points 0 and a context opposes.
    bear = intraday(ctx("1d", "bear"), ctx("4h", "bear"))
    s = score(cfg, context=bear)
    assert s.counter_trend
    assert by_code(s)["htf_trend"] == (0, "none")
    neutral = intraday(ctx("1d", "neutral"), ctx("4h", "neutral"))
    assert not score(cfg, context=neutral).counter_trend
    assert not score(cfg, context=intraday(ctx("1d", "bull"), ctx("4h", "bear"))).counter_trend
    assert (
        score_candidate(
            cand(context=bear), cfg, normal_spread=12, price_scale=5, counter_trend="hide"
        )
        is None
    )


def test_combined_rounding_half_up_and_high_quality(cfg):
    assert combined(60, 60, cfg) == 60
    assert combined(65, 50, cfg) == 59
    assert high_quality(60, cfg)
    assert not high_quality(59, cfg)
    odd = dataclasses.replace(cfg, q_permille=650, c_permille=350)
    assert combined(0, 10, odd) == 4  # 3.5 rounds up, never Python round()


def test_scoring_config_rejects_bad_weights():
    doc = json.loads((REPO / "config" / "rules" / "r1.0.json").read_text(encoding="utf-8"))
    weights = {"scoring_version": "s1.0", **doc["weights"]}
    bad = json.loads(json.dumps(weights))
    bad["q"]["sweep"] = 21  # Q maxima must sum to 100
    with pytest.raises(ScoringConfigError, match="Q"):
        ScoringConfig.from_json(bad)
    bad = json.loads(json.dumps(weights))
    bad["c_permille"] = 401
    with pytest.raises(ScoringConfigError, match="permille"):
        ScoringConfig.from_json(bad)
    bad = json.loads(json.dumps(weights))
    bad["q"]["fvg"] = 20.0
    with pytest.raises(ScoringConfigError, match="integer"):
        ScoringConfig.from_json(bad)


# ---------------------------------------------------------------- re-evaluation

KEY = SeriesKey("EUR_USD", "15m", "r1.0", H)


def ltf_break(at, direction="bull", tf="15m", structure="internal", type_="bos"):
    key = dataclasses.replace(KEY, timeframe=tf)
    return key.event(type_, structure, direction, 108_040, at - timedelta(minutes=30), at)


def test_ltf_confirmation_adds_20_once(cfg):
    s = score(cfg)
    touch = T + timedelta(hours=3)  # close of the touching 1H candle (it opened at T + 2 h)
    trans = [(OB, "touched", touch)]
    early = ltf_break(touch - timedelta(hours=1, minutes=15))  # before the touching candle opened
    late = ltf_break(touch + timedelta(minutes=15))
    wrong_dir = ltf_break(touch - timedelta(minutes=30), direction="bear")
    external = ltf_break(touch - timedelta(minutes=30), structure="external")
    wrong_tf = ltf_break(touch - timedelta(minutes=30), tf="1h")
    events = [early, wrong_dir, external, wrong_tf, late]
    s2 = reevaluate(s, trans, events, touch + timedelta(hours=1), cfg)
    assert s2.c == s.c + 20
    assert s2.ltf_confirmed_at == late.confirm_time
    assert (s2.revision, s2.revisions[-1].reason) == (2, "ltf_confirmation")
    assert by_code(s2)["ltf_confirm"] == (20, "confirmed")
    assert s2.q == s.q
    assert s2.combined == combined(s2.q, s2.c, cfg)
    # Once only: a later break changes nothing.
    again = ltf_break(touch + timedelta(minutes=45))
    assert reevaluate(s2, trans, [late, again], touch + timedelta(hours=2), cfg) is None


def test_ltf_confirmation_needs_a_touch(cfg):
    s = score(cfg)
    brk = ltf_break(T + timedelta(minutes=30))
    assert reevaluate(s, [], [brk], T + timedelta(hours=1), cfg) is None
    # The 5m timeframe confirms an intraday setup too.
    touch = T + timedelta(hours=1)
    five = ltf_break(touch - timedelta(minutes=20), tf="5m")
    s2 = reevaluate(s, [(OB, "touched", touch)], [five], touch, cfg)
    assert s2.ltf_confirmed_at == five.confirm_time


def test_reevaluate_ignores_wall_clock(cfg):
    s = score(cfg)
    touch = T + timedelta(hours=3)
    brk = ltf_break(touch + timedelta(minutes=15))
    trans = [(OB, "touched", touch), (OB, "invalidated", touch + timedelta(hours=2))]
    # Only what is known as of the batch close counts: later rows are ignored, and every call
    # with the same inputs gives the same result.
    assert reevaluate(s, trans, [brk], touch, cfg) is None
    first = reevaluate(s, trans, [brk], touch + timedelta(hours=1), cfg)
    second = reevaluate(s, trans, [brk], touch + timedelta(hours=1), cfg)
    assert first == second
    assert first.status == "confirmed"
    assert first.ltf_confirmed_at == brk.confirm_time


def test_zone_invalidated_sets_status(cfg):
    s = score(cfg)
    when = T + timedelta(hours=5)
    s2 = reevaluate(s, [(OB, "invalidated", when)], [], when, cfg)
    assert (s2.status, s2.status_time, s2.revision) == ("invalidated", when, 2)
    assert s2.revisions[-1].reason == "zone_invalidated"
    assert (s2.q, s2.c) == (s.q, s.c)
    assert reevaluate(s2, [(OB, "invalidated", when)], [], when, cfg) is None  # final
    s3 = reevaluate(s, [(OB, "expired", when)], [], when, cfg)
    assert (s3.status, s3.revisions[-1].reason) == ("expired", "zone_expired")
    # A filled zone does not change the setup; another zone's invalidation neither.
    other = [(OB, "filled", when), (FVG, "invalidated", when)]
    assert reevaluate(s, other, [], when, cfg) is None
    # Without an OB the FVG is the primary zone.
    fvg_only = score(cfg, ob_zone_id=None)
    assert reevaluate(fvg_only, [(FVG, "invalidated", when)], [], when, cfg).status == "invalidated"


def test_confirmation_then_invalidation_in_one_batch(cfg):
    s = score(cfg)
    touch = T + timedelta(hours=3)
    brk = ltf_break(touch + timedelta(minutes=15))
    trans = [(OB, "touched", touch), (OB, "invalidated", touch + timedelta(hours=1))]
    s2 = reevaluate(s, trans, [brk], touch + timedelta(hours=1), cfg)
    assert [r.reason for r in s2.revisions] == ["created", "ltf_confirmation", "zone_invalidated"]
    assert (s2.status, s2.revision) == ("invalidated", 3)


# ---------------------------------------------------------------- explanation


def test_explanation_lists_met_then_missed(cfg):
    s = score(cfg, sweep_event_id=None, patterns=("bos", "displacement", "fvg", "ob"),
              context=intraday(ctx("1d", "bull"), ctx("4h", "neutral")))  # fmt: skip
    text = explain(s)
    head, rest = text.split(" Met: ", 1)
    met, missed = rest.split(" Missed: ", 1)
    assert head == f"Bullish BOS setup, combined {s.combined} (Q {s.q}, C {s.c})."
    assert met.startswith("A bullish BOS closed above 1.08100 with a 2-candle strong displacement")
    assert "The 1D trend is bullish but the 4H trend is not (+20 of 40)." in met
    assert (
        "The nearest buy-side level 1.08300 is 2.50 "
        + chr(0xD7)
        + " ATR above the zone (+15 of 15)."
        in met
    )
    assert missed.startswith("No same-direction liquidity sweep")
    assert "Price has not returned to the zone yet (0 of 20)." in missed
    assert "(+" not in missed
    met_codes = [f.code for f in s.factors if f.points > 0]
    positions = [met.index(sentence) for sentence in sentences(s) if sentence in met]
    assert positions == sorted(positions)
    assert len(positions) == len(met_codes)
    assert s.explanation == text


def test_explanation_bearish_and_jpy_scale(cfg):
    s = score(cfg, price_scale=3, direction="bear", break_type="choch", break_level=150_123,
              zone_low=150_200, zone_high=150_260, invalidation=150_260, opposing_level=None,
              patterns=("choch", "displacement", "fvg", "ob"),
              context=intraday(ctx("1d", "bear"), ctx("4h", "bear")))  # fmt: skip
    text = explain(s)
    assert s.explanation == text
    assert text.startswith("Bearish CHoCH setup, combined")
    assert "A bearish CHoCH closed below 150.123" in text
    assert "The 1D and 4H trends are bearish (+40 of 40)." in text
    assert "No opposing liquidity level is known (0 of 15)." in text


def test_scores_every_engine_candidate(cfg, settings_obj):
    # Real candidates from 2,000 synthetic 5m candles and the timeframes built from them.
    from builders import aggregate, impulsive

    from tradelens_engine.multi import run_multi
    from tradelens_engine.settings import Settings

    five = impulsive(2000)
    series = {"5m": five} | {tf: aggregate(five, tf) for tf in ("15m", "1h", "4h", "1d")}
    out = run_multi(series, Settings.from_json(settings_obj()), instrument="EUR_USD",
                    rule_version="r1.0")  # fmt: skip
    cands = [c for r in out.values() for c in r.setup_candidates]
    assert cands
    for c in cands:
        s = score_candidate(c, cfg, normal_spread=12, price_scale=5)
        assert 0 <= s.q <= 100 and 0 <= s.c <= 100
        assert s.combined == combined(s.q, s.c, cfg)
        assert len(s.factors) == 10
        assert s.explanation.startswith(("Bullish", "Bearish"))
