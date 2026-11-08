"""Displacement, order blocks, lifecycle and setup candidates through step/run (DD 3.4, 3.6)."""

import pytest
from scenario import BASE, EXACT3, LATE, NO_DISP, TOUCHED, candles

from tradelens_engine.run import run
from tradelens_engine.series import SeriesState
from tradelens_engine.settings import Settings
from tradelens_engine.step import step


@pytest.fixture
def cfg(settings_obj):
    return Settings.from_json(settings_obj(internal_pivot=2, external_pivot=8))


def go(rows, cfg, tf="1h"):
    return run(candles(rows, tf), cfg, instrument="EUR_USD", timeframe=tf, rule_version="r1.0")


def obs(result):
    return [z for z in result.zones if z.kind == "ob"]


def test_scenario_events(cfg):
    res = go(BASE, cfg)
    c = candles(BASE)
    internal = [(e.type, e.direction, e.level, e.confirm_time) for e in res.events
                if e.structure == "internal" and e.type in ("bos", "choch")]  # fmt: skip
    assert internal == [("bos", "bull", 1060, c[28].close_time)]
    disp = [(e.origin_time, e.confirm_time, e.level, dict(e.details)) for e in res.events
            if e.type == "displacement" and e.confirm_time == c[26].close_time]  # fmt: skip
    assert disp == [(c[26].open_time, c[26].close_time, None, {"candles": 1, "strong": False})]
    sweeps = [(e.direction, e.level, e.confirm_time) for e in res.events if e.type == "sweep"]
    assert ("bull", 990, c[18].close_time) in sweeps


def test_ob_promoted_full_range_at_the_break(cfg):
    res = go(BASE, cfg)
    c = candles(BASE)
    [ob] = obs(res)
    assert (ob.direction, ob.low, ob.high) == ("bull", 1003, 1025)
    assert (ob.origin_time, ob.confirm_time) == (c[25].open_time, c[28].close_time)
    assert ob.pre_confirmation_touch is False
    bos = next(e for e in res.events if e.type == "bos" and e.structure == "internal")
    assert ob.source_event_id == bos.id


def test_ob_detected_written_only_at_promotion(cfg):
    c = candles(BASE)
    state, outputs = SeriesState(), []
    for candle in c:
        state, out = step(state, candle, cfg, instrument="EUR_USD", timeframe="1h",
                          rule_version="r1.0")  # fmt: skip
        outputs.append(out)
    ob_id = obs(go(BASE, cfg))[0].id
    for i, out in enumerate(outputs[:28]):
        assert all(t[0] != ob_id for t in out.zone_transitions), i
    assert [t for t in outputs[28].zone_transitions if t[0] == ob_id] == [
        (ob_id, "detected", c[26].close_time),  # the displacement close
        (ob_id, "confirmed", c[28].close_time),  # the break close
    ]
    assert [z.id for z in outputs[28].new_zones if z.kind == "ob"] == [ob_id]


def test_move_without_a_break_within_3_candles_leaves_no_rows(cfg):
    late = go(LATE, cfg)
    assert any(e.type == "bos" and e.structure == "internal" for e in late.events)
    assert obs(late) == []
    assert late.setup_candidates == ()
    exact = go(EXACT3, cfg)
    assert len(obs(exact)) == 1
    assert len(exact.setup_candidates) == 1


def test_touched_before_confirmation_flagged(cfg):
    [ob] = obs(go(TOUCHED, cfg))
    assert ob.pre_confirmation_touch is True
    [setup] = go(TOUCHED, cfg).setup_candidates
    assert setup.ob_pre_touched is True


def test_setup_candidate_on_1h(cfg):
    res = go(BASE, cfg)
    c = candles(BASE)
    [s] = res.setup_candidates
    [ob] = obs(res)
    fvg = next(z for z in res.zones if z.kind == "fvg" and (z.low, z.high) == (1025, 1045))
    bos = next(e for e in res.events if e.type == "bos" and e.structure == "internal")
    assert (s.timeframe, s.profile, s.direction, s.break_type) == ("1h", "intraday", "bull", "bos")
    assert s.patterns == ("bos", "displacement", "sweep", "fvg", "ob")
    assert (s.break_event_id, s.ob_zone_id, s.fvg_zone_id) == (bos.id, ob.id, fvg.id)
    assert s.invalidation == 1003  # far edge of the primary zone (the OB)
    assert s.ob_pre_touched is False and s.displacement_strong is False
    assert s.spread == 2
    assert s.sessions == ("london", "new_york")  # bar 29 opens 08:00 New York
    assert s.confirm_time == c[28].close_time and s.origin_time == ob.origin_time
    assert len(s.id) == 32 and s.context is None


def test_no_displacement_no_candidate(cfg):
    res = go(NO_DISP, cfg)
    assert any(e.type == "bos" and e.structure == "internal" for e in res.events)
    assert res.setup_candidates == () and obs(res) == []


def test_setups_only_on_15m_1h_4h(cfg):
    assert [s.profile for s in go(BASE, cfg, "15m").setup_candidates] == ["scalping"]
    assert [s.profile for s in go(BASE, cfg, "4h").setup_candidates] == ["swing"]
    for tf in ("5m", "1d"):
        res = go(BASE, cfg, tf)
        assert res.setup_candidates == (), tf
        assert len(obs(res)) == 1, tf  # order blocks exist on every timeframe


def test_zone_lifecycle_through_step(cfg):
    rows = [*BASE, (1072, 1014, 1070, 1030), (1040, 990, 1030, 1000)]
    res = go(rows, cfg)
    c = candles(rows)
    ob_id = obs(res)[0].id
    moves = [(s, t) for z, s, t in res.zone_transitions if z == ob_id]
    assert moves == [
        ("detected", c[26].close_time), ("confirmed", c[28].close_time),
        ("touched", c[29].close_time), ("mitigated_50", c[29].close_time),
        ("filled", c[30].close_time), ("invalidated", c[30].close_time),
    ]  # fmt: skip
    assert all(z.id != ob_id for z in (zs.zone for zs in res.state.zones))


def test_two_displacements_sharing_one_ob_keep_it_in_the_setup(cfg):
    from scenario import SHARED

    res = go(SHARED, cfg)
    disp = [e for e in res.events if e.type == "displacement"
            and e.confirm_time >= candles(SHARED)[26].close_time]  # fmt: skip
    assert [dict(e.details)["candles"] for e in disp] == [1, 2]
    [ob] = obs(res)
    [s] = res.setup_candidates
    assert s.ob_zone_id == ob.id and "ob" in s.patterns
    assert s.displacement_event_id == disp[-1].id
