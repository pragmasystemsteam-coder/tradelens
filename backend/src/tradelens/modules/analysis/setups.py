"""Setup scoring in the worker: score new candidates, re-evaluate open setups (DD 3.6; task 2.3).

After a close batch is stepped, every setup candidate it produced is scored (revision 1,
``score_candidate`` plus ``explain``), and every open setup of the instrument - stored ones and
the ones just created - is re-evaluated with what the batch saw: zone transitions and events,
as of the batch close (``reevaluate``; the wall clock is never read). The result is saved in
the same transaction as the batch (``SqlAnalysisStore.save_batch``).

Stored setups are rebuilt from ``setups.engine`` (migration 0003): the candidate and the
factors with their template values, so a later revision can rewrite the explanation exactly.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from tradelens_engine.codec import decode, encode
from tradelens_engine.events import Event
from tradelens_engine.multi import BatchResult
from tradelens_engine.scoring import (
    Factor,
    ScoringConfig,
    Setup,
    high_quality,
    reevaluate,
    score_candidate,
)
from tradelens_engine.setups import SetupCandidate
from tradelens_engine.timefmt import iso, parse_iso

Transition = tuple[str, str, datetime]


@dataclass(frozen=True, slots=True)
class InstrumentMeta:
    """What scoring and the setup rows need about an instrument (config/instruments.json)."""

    asset_class: str
    price_scale: int
    normal_spread: int


@dataclass(frozen=True, slots=True)
class SetupChanges:
    """Setups one batch created or revised (a revised setup carries only its new revisions)."""

    created: tuple[Setup, ...] = ()
    revised: tuple[Setup, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.created or self.revised)

    def all(self) -> tuple[Setup, ...]:
        """Created then revised setups."""
        return (*self.created, *self.revised)


def _batch_facts(result: BatchResult) -> tuple[list[Transition], list[Event], datetime | None]:
    transitions: list[Transition] = []
    events: list[Event] = []
    for outs in result.outputs.values():
        for out in outs:
            transitions.extend(out.zone_transitions)
            events.extend(out.events)
    as_of = max((t for _, t in result.steps), default=None)
    return transitions, events, as_of


class SetupScorer:
    """Scores the candidates of a batch and re-evaluates open setups at the batch close."""

    def __init__(
        self,
        weights: ScoringConfig,
        *,
        counter_trend: str,
        instruments: Mapping[str, InstrumentMeta],
    ) -> None:
        """Wire the scorer.

        Args:
            weights: Weights of the active scoring version (``rule_versions.weights``).
            counter_trend: ``warn`` or ``hide`` from the official settings (FR-MTF-06).
            instruments: Instrument code to its scoring metadata.
        """
        self.weights = weights
        self.counter_trend = counter_trend
        self.instruments = dict(instruments)

    def _new(self, cand: SetupCandidate) -> Setup | None:
        meta = self.instruments[cand.instrument]
        return score_candidate(cand, self.weights, normal_spread=meta.normal_spread,
                               price_scale=meta.price_scale,
                               counter_trend=self.counter_trend)  # fmt: skip

    def score(
        self, instrument: str, result: BatchResult, open_setups: Sequence[Setup]
    ) -> SetupChanges:
        """Score and re-evaluate.

        Args:
            instrument: The instrument of the batch.
            result: The stepped batch.
            open_setups: Confirmed setups of the instrument as last saved (revisions empty).

        Returns:
            Created setups (all their revisions) and revised setups (only the new revisions).
        """
        transitions, events, as_of = _batch_facts(result)
        created: dict[str, Setup] = {}
        for outs in result.outputs.values():
            for out in outs:
                for cand in out.setup_candidates:
                    s = self._new(cand) if cand.instrument == instrument else None
                    if s is not None:
                        created.setdefault(s.id, s)
        revised: list[Setup] = []
        if as_of is not None:
            for sid, s in list(created.items()):
                r = reevaluate(s, transitions, events, as_of, self.weights)
                if r is not None:
                    created[sid] = r
            for s in open_setups:
                if s.id in created:
                    continue
                r = reevaluate(s, transitions, events, as_of, self.weights)
                if r is not None:
                    revised.append(replace(r, revisions=r.revisions[len(s.revisions) :]))
        return SetupChanges(tuple(created.values()), tuple(revised))


def _plain(value: Any) -> Any:  # noqa: ANN401 - factor template values (str, int, tuples)
    if isinstance(value, tuple):
        return [_plain(v) for v in value]
    return value


def _tuples(value: Any) -> Any:  # noqa: ANN401 - inverse of _plain
    if isinstance(value, list):
        return tuple(_tuples(v) for v in value)
    return value


def factor_json(f: Factor) -> dict[str, Any]:
    """A factor with its template values (``setups.engine``)."""
    return {**f.to_json(), "args": [[k, _plain(v)] for k, v in f.args]}


def setup_to_engine_json(s: Setup) -> dict[str, Any]:
    """Everything needed to rebuild ``s`` for re-evaluation (stored in ``setups.engine``)."""
    return {
        "candidate": encode(s.candidate), "scoring_version": s.scoring_version,
        "price_scale": s.price_scale, "q": s.q, "c": s.c, "combined": s.combined,
        "counter_trend": s.counter_trend, "factors": [factor_json(f) for f in s.factors],
        "status": s.status, "status_time": iso(s.status_time), "revision": s.revision,
        "ltf_confirmed_at": None if s.ltf_confirmed_at is None else iso(s.ltf_confirmed_at),
        "explanation": s.explanation,
    }  # fmt: skip


def setup_from_engine_json(doc: Mapping[str, Any], weights: ScoringConfig) -> Setup:
    """Rebuild a stored setup (its earlier revisions are not needed: ``revisions`` is empty)."""
    factors = tuple(
        Factor(f["code"], f["score"], f["points"], f["max"], f["reason"],
               tuple((k, _tuples(v)) for k, v in f["args"]))
        for f in doc["factors"]
    )  # fmt: skip
    ltf = doc["ltf_confirmed_at"]
    return Setup(
        candidate=decode(SetupCandidate, doc["candidate"]),
        scoring_version=doc["scoring_version"], price_scale=doc["price_scale"], q=doc["q"],
        c=doc["c"], combined=doc["combined"],
        high_quality=high_quality(doc["combined"], weights),
        counter_trend=doc["counter_trend"], factors=factors, status=doc["status"],
        status_time=parse_iso(doc["status_time"]), revision=doc["revision"],
        ltf_confirmed_at=None if ltf is None else parse_iso(ltf), revisions=(),
        explanation=doc["explanation"],
    )  # fmt: skip


def scorer_for(
    weights: Mapping[str, Any], counter_trend: str, instruments: Mapping[str, InstrumentMeta]
) -> SetupScorer:
    """A scorer from the stored ``rule_versions.weights`` (keeps the engine inside analysis)."""
    return SetupScorer(ScoringConfig.from_json(dict(weights)), counter_trend=counter_trend,
                       instruments=instruments)  # fmt: skip
