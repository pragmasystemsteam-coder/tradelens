"""Current candidates for the analysis panel (CR-006): display only, never stored or ranked.

Approved rules: the latest internal BOS/CHoCH per direction in the last 50 candles that did not
make a setup; factors scored with the normal weights and missed gates marked; when no OB/FVG is
in the move, the nearest open same-direction zone within 1 x ATR is "nearby".
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tradelens_engine.scoring import ScoringConfig
from tradelens_engine.scoring.candidates import EventIn, LevelIn, ZoneIn, current_candidates

REPO = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 11, 18, 4, 0, tzinfo=UTC)
H1 = 3600
ATR = 100_000  # 100 units
CONST = {"disp_break_window": 3, "sweep_window_bars": 10}
LEVELS = (LevelIn(108_400, "buy"),)


@pytest.fixture
def w():
    doc = json.loads((REPO / "config" / "rules" / "r1.0.json").read_text(encoding="utf-8"))
    return ScoringConfig.from_json({"scoring_version": doc["scoring_version"], **doc["weights"]})


def at(hours_ago):
    return NOW - timedelta(hours=hours_ago)


def ev(eid, etype, direction="bull", hours_ago=1, structure="internal", level=108_100, **kw):
    origin = at(hours_ago + kw.pop("span", 1))
    return EventIn(eid, etype, structure, direction, None if etype == "displacement" else level,
                   origin, at(hours_ago), **kw)  # fmt: skip


def zone(zid, kind="fvg", direction="bull", low=108_000, high=108_050, hours_ago=2,
         state="confirmed"):  # fmt: skip
    return ZoneIn(zid, kind, direction, low, high, state, at(hours_ago + 1), at(hours_ago))


def run(w, events, zones=(), levels=LEVELS, setup_breaks=frozenset(),
        atr=ATR):  # fmt: skip
    return current_candidates(
        instrument="EUR_USD", timeframe="1h", profile="intraday", settings_hash="h" * 64,
        rule_version="r1.0", now=NOW, tf_seconds=H1, events=events, zones=zones,
        levels=levels, atr_k=atr, context=None, setup_break_ids=setup_breaks,
        sessions=("london",), spread=0, constants=CONST, weights=w, normal_spread=12,
    )  # fmt: skip


def checks(c):
    return {k.code: k.met for k in c.checks}


def test_full_candidate_meets_every_gate_and_is_scored(w):
    events = [ev("d1", "displacement", hours_ago=2, strong=True, candles=2, span=2),
              ev("s1", "sweep", hours_ago=4), ev("b1", "bos", hours_ago=1)]  # fmt: skip
    [c] = run(w, events, zones=[zone("z1", "fvg", hours_ago=2)])
    assert c.direction == "bull" and c.break_event.id == "b1"
    assert checks(c) == {"break": True, "displacement": True, "zone_in_move": True}
    assert c.patterns == ("bos", "displacement", "sweep", "fvg")
    assert c.zone is not None and c.zone.id == "z1" and not c.zone_nearby
    assert c.q > 0 and c.combined > 0
    assert {f.code for f in c.factors} >= {"break", "sweep", "fvg", "room", "htf_trend"}


def test_missed_displacement_is_marked_and_still_scored(w):
    [c] = run(w, [ev("b1", "choch", hours_ago=1)], zones=[zone("z1", hours_ago=2)])
    assert checks(c) == {"break": True, "displacement": False, "zone_in_move": False}
    assert c.displacement is None
    assert c.patterns == ("choch",)
    assert c.combined >= 0


def test_nearby_zone_within_one_atr_when_none_in_the_move(w):
    events = [ev("d1", "displacement", hours_ago=1, candles=1, span=1),
              ev("b1", "bos", hours_ago=1)]  # fmt: skip
    near = zone("zn", "ob", low=108_020, high=108_060, hours_ago=20)  # 40 units from the break
    far = zone("zf", "ob", low=107_500, high=107_550, hours_ago=20)  # 550 units: beyond 1 ATR
    [c] = run(w, events, zones=[far, near])
    assert c.zone is not None and c.zone.id == "zn" and c.zone_nearby
    assert checks(c)["zone_in_move"] is False
    [c2] = run(w, events, zones=[far])
    assert c2.zone is None


def test_break_that_made_a_setup_is_not_a_candidate(w):
    assert run(w, [ev("b1", "bos")], setup_breaks=frozenset({"b1"})) == []


def test_breaks_older_than_50_candles_or_external_are_ignored(w):
    assert run(w, [ev("b1", "bos", hours_ago=51)]) == []
    assert run(w, [ev("b1", "bos", structure="external")]) == []


def test_one_candidate_per_direction_latest_break_wins(w):
    events = [ev("b1", "bos", hours_ago=5), ev("b2", "bos", hours_ago=2),
              ev("x1", "bos", direction="bear", hours_ago=3, level=108_500)]  # fmt: skip
    got = {c.direction: c.break_event.id for c in run(w, events)}
    assert got == {"bull": "b2", "bear": "x1"}


def test_closed_zones_are_never_nearby(w):
    used = zone("zu", "ob", low=108_020, high=108_060, hours_ago=20, state="invalidated")
    [c] = run(w, [ev("b1", "bos", hours_ago=1)], zones=[used])
    assert c.zone is None
