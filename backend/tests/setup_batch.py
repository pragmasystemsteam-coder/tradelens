"""A hand-built close batch with one setup, for the task 2.3 worker and database tests.

The batch holds what a real one would: the break event and the OB and FVG zones the setup
points to (so foreign keys hold), the setup candidate, and a 1H series state. Later batches
add zone transitions and a confirmation BOS to drive re-evaluation.
"""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tradelens.modules.analysis.process import CloseBatch
from tradelens.modules.analysis.setups import InstrumentMeta, SetupScorer
from tradelens_engine.context import HigherTfContext, TfContext
from tradelens_engine.events import Event, Zone
from tradelens_engine.multi import BatchResult
from tradelens_engine.scoring import ScoringConfig
from tradelens_engine.series import SeriesState
from tradelens_engine.setups import SetupCandidate
from tradelens_engine.step import StepOutput

REPO = Path(__file__).resolve().parents[2]
T = datetime(2026, 11, 11, 14, 0, tzinfo=UTC)  # 1H break close
H = "a" * 64
SID, BREAK, OB, FVG = "5" * 32, "b" * 32, "0" * 32, "f" * 32
META = {"EUR_USD": InstrumentMeta(asset_class="forex", price_scale=5, normal_spread=12)}


def weights():
    doc = json.loads((REPO / "config" / "rules" / "r1.0.json").read_text(encoding="utf-8"))
    return ScoringConfig.from_json({"scoring_version": doc["scoring_version"], **doc["weights"]})


def scorer():
    return SetupScorer(weights(), counter_trend="warn", instruments=META)


def _ctx(tf):
    return TfContext(tf, True, "bull", 400_000, T - timedelta(hours=1), ())


def candidate():
    return SetupCandidate(
        id=SID, instrument="EUR_USD", timeframe="1h", profile="intraday", direction="bull",
        break_event_id=BREAK, break_type="bos", patterns=("bos", "displacement", "fvg", "ob"),
        sessions=("london",), spread=10, atr_k=100_000, displacement_event_id="d" * 32,
        displacement_strong=True, sweep_event_id=None, ob_zone_id=OB, fvg_zone_id=FVG,
        ob_pre_touched=False, invalidation=108_000, opposing_level=108_300,
        origin_time=T - timedelta(hours=3), confirm_time=T, settings_hash=H,
        rule_version="r1.0", zone_low=108_000, zone_high=108_050, break_level=108_100,
        displacement_candles=2,
        context=HigherTfContext("intraday", (_ctx("1d"), _ctx("4h"))),
    )  # fmt: skip


def event(eid, tf, at, etype="bos"):
    return Event(eid, "EUR_USD", tf, etype, "internal", "bull", 108_100,
                 at - timedelta(hours=1), at, H, "r1.0")  # fmt: skip


def zone(zid, kind):
    return Zone(zid, kind, "EUR_USD", "1h", "bull", 108_000, 108_050,
                T - timedelta(hours=3), T, H, "r1.0")  # fmt: skip


def state(last):
    return replace(SeriesState(), last_open_time=last - timedelta(hours=1), last_close_time=last)


def make_batch(*, first=True, transitions=(), events=(), last=T, open_setups=()):
    """A 1H close batch scored by the real scorer.

    Args:
        first: The batch that creates the setup (break event, zones, candidate).
        transitions: ``(zone_id, state, close_time)`` seen by this batch.
        events: Extra events (e.g. a confirmation BOS).
        last: Close time of the batch.
        open_setups: Setups already stored (for re-evaluation).
    """
    out = StepOutput(
        events=((event(BREAK, "1h", T),) if first else ()) + tuple(events),
        new_zones=(zone(OB, "ob"), zone(FVG, "fvg")) if first else (),
        zone_transitions=tuple(transitions),
        setup_candidates=(candidate(),) if first else (),
    )  # fmt: skip
    result = BatchResult(states={"1h": state(last)}, outputs={"1h": (out,)},
                         steps=(("1h", last),))  # fmt: skip
    changes = scorer().score("EUR_USD", result, list(open_setups))
    return CloseBatch("EUR_USD", H, "r1.0", result, changes, "forex")
