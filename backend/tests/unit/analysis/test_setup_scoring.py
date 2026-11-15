"""Worker setup scoring: new setups, batch-end re-evaluation, storage round trip (task 2.3).

The scorer turns the setup candidates of one close batch into scored setups (revision 1) and
re-evaluates every open setup of the instrument with what the batch saw (zone transitions and
confirmation-timeframe events), using only facts up to the batch close (DD 3.6).
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tradelens.modules.analysis.setups import (
    InstrumentMeta,
    SetupScorer,
    setup_from_engine_json,
    setup_to_engine_json,
)
from tradelens_engine.context import HigherTfContext, TfContext
from tradelens_engine.events import Event
from tradelens_engine.multi import BatchResult
from tradelens_engine.scoring import ScoringConfig, explain
from tradelens_engine.setups import SetupCandidate
from tradelens_engine.step import StepOutput

REPO = Path(__file__).resolve().parents[4]
T = datetime(2026, 11, 11, 14, 0, tzinfo=UTC)  # 1H break close
H = "h" * 64
OB, FVG = "o" * 32, "f" * 32
META = {"EUR_USD": InstrumentMeta(asset_class="forex", price_scale=5, normal_spread=12)}


@pytest.fixture
def weights():
    doc = json.loads((REPO / "config" / "rules" / "r1.0.json").read_text(encoding="utf-8"))
    return ScoringConfig.from_json({"scoring_version": doc["scoring_version"], **doc["weights"]})


def ctx(tf, trend):
    return TfContext(tf, True, trend, 400_000, T - timedelta(hours=1), ())


def cand(**kw):
    base = dict(  # noqa: C408 - keyword form mirrors the dataclass
        id="s" * 32, instrument="EUR_USD", timeframe="1h", profile="intraday", direction="bull",
        break_event_id="b" * 32, break_type="bos",
        patterns=("bos", "displacement", "fvg", "ob"), sessions=("london",),
        spread=10, atr_k=100_000, displacement_event_id="d" * 32, displacement_strong=True,
        sweep_event_id=None, ob_zone_id=OB, fvg_zone_id=FVG, ob_pre_touched=False,
        invalidation=108_000, opposing_level=108_300, origin_time=T - timedelta(hours=3),
        confirm_time=T, settings_hash=H, rule_version="r1.0", zone_low=108_000,
        zone_high=108_050, break_level=108_100, displacement_candles=2,
        context=HigherTfContext("intraday", (ctx("1d", "bull"), ctx("4h", "bull"))),
    )  # fmt: skip
    base.update(kw)
    return SetupCandidate(**base)


def bos(tf, at, direction="bull", eid="e" * 32):
    return Event(eid, "EUR_USD", tf, "bos", "internal", direction, 108_060,
                 at - timedelta(minutes=30), at, H, "r1.0")  # fmt: skip


def batch(*, candidates=(), transitions=(), events=(), last=T):
    out = StepOutput(events=tuple(events), zone_transitions=tuple(transitions),
                     setup_candidates=tuple(candidates))  # fmt: skip
    return BatchResult(states={}, outputs={"1h": (out,)}, steps=(("1h", last),))


def scorer(weights):
    return SetupScorer(weights, counter_trend="warn", instruments=META)


def test_candidate_becomes_revision_one(weights):
    changes = scorer(weights).score("EUR_USD", batch(candidates=[cand()]), open_setups=[])
    (s,) = changes.created
    assert (s.id, s.status, s.revision) == ("s" * 32, "confirmed", 1)
    assert [r.reason for r in s.revisions] == ["created"]
    assert s.explanation == explain(s)
    assert changes.revised == ()


def test_batch_end_reevaluation_adds_ltf_revision(weights):
    s = scorer(weights).score("EUR_USD", batch(candidates=[cand()]), open_setups=[]).created[0]
    touch = T + timedelta(hours=2)
    later = batch(transitions=[(OB, "touched", touch)],
                  events=[bos("15m", touch + timedelta(minutes=15))],
                  last=touch + timedelta(minutes=15))  # fmt: skip
    changes = scorer(weights).score("EUR_USD", later, open_setups=[s])
    (r,) = changes.revised
    assert [v.reason for v in r.revisions] == ["ltf_confirmation"]
    assert r.revision == 2
    assert r.c == s.c + weights.ltf_confirm
    assert r.explanation == explain(r)


def test_zone_invalidated_ends_setup(weights):
    s = scorer(weights).score("EUR_USD", batch(candidates=[cand()]), open_setups=[]).created[0]
    end = T + timedelta(hours=5)
    changes = scorer(weights).score(
        "EUR_USD", batch(transitions=[(OB, "invalidated", end)], last=end), open_setups=[s]
    )
    (r,) = changes.revised
    assert (r.status, r.status_time, r.revision) == ("invalidated", end, 2)


def test_facts_after_the_batch_close_are_ignored(weights):
    s = scorer(weights).score("EUR_USD", batch(candidates=[cand()]), open_setups=[]).created[0]
    future = T + timedelta(hours=9)
    changes = scorer(weights).score(
        "EUR_USD",
        batch(transitions=[(OB, "invalidated", future)], last=T + timedelta(hours=1)),
        open_setups=[s],
    )
    assert changes.revised == ()


def test_same_batch_creates_then_invalidates(weights):
    end = T + timedelta(hours=1)
    changes = scorer(weights).score(
        "EUR_USD",
        batch(candidates=[cand()], transitions=[(OB, "invalidated", end)], last=end),
        open_setups=[],
    )
    (s,) = changes.created
    assert [r.reason for r in s.revisions] == ["created", "zone_invalidated"]
    assert s.status == "invalidated"


def test_engine_json_round_trip_keeps_explanation(weights):
    s = scorer(weights).score("EUR_USD", batch(candidates=[cand()]), open_setups=[]).created[0]
    back = setup_from_engine_json(json.loads(json.dumps(setup_to_engine_json(s))), weights)
    assert back.id == s.id
    assert (back.q, back.c, back.combined, back.status, back.revision) == (
        s.q, s.c, s.combined, s.status, s.revision)  # fmt: skip
    assert explain(back) == s.explanation


def test_hidden_counter_trend_creates_nothing(weights):
    bear_ctx = HigherTfContext("intraday", (ctx("1d", "bear"), ctx("4h", "bear")))
    hide = SetupScorer(weights, counter_trend="hide", instruments=META)
    changes = hide.score("EUR_USD", batch(candidates=[cand(context=bear_ctx)]), open_setups=[])
    assert changes.created == ()
