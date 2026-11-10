"""Scoring types: weights, factors, revisions and the scored setup (DD 3.6, 6.3).

Every number is an integer (DD-5). Weights come from ``rule_versions.weights`` (config/rules),
so a new rule version can change them without code.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from tradelens_engine.setups import SetupCandidate

PERMILLE = 1000
SCORE_MAX = 100
PAIR = 2
Score = Literal["Q", "C"]
Args = tuple[tuple[str, Any], ...]


class ScoringConfigError(ValueError):
    """Weights that must not be used."""


def _int(path: str, value: object) -> int:
    if type(value) is not int or value < 0:
        raise ScoringConfigError(f"{path} must be a non-negative integer (DD-5), got {value!r}")
    return value


def _pair(path: str, value: object) -> tuple[int, int]:
    if not isinstance(value, list) or len(value) != PAIR:
        raise ScoringConfigError(f"{path} must be [full, partial]")
    return _int(path, value[0]), _int(path, value[1])


@dataclass(frozen=True, slots=True)
class ScoringConfig:
    """Weights of one scoring version (``rule_versions.weights``)."""

    scoring_version: str
    q_permille: int
    c_permille: int
    high_quality: int
    break_strong: int
    break_minimal: int
    sweep: int
    fvg: int
    ob_fresh: int
    room_full_m: int
    room_full: int
    room_part_m: int
    room_part: int
    spread_session: int
    trend_all: int
    trend_one: int
    htf_zone: int
    ltf_confirm: int
    no_conflict: int
    conflict_distance_m: int

    @classmethod
    def from_json(cls, w: Mapping[str, Any]) -> ScoringConfig:
        """Parse and check weights (DD 6.3).

        Raises:
            ScoringConfigError: On a missing key, a float or negative value, permille that do
                not sum to 1000, or Q or C maxima that do not sum to 100.
        """
        try:
            q, c = w["q"], w["c"]
            room, conflict = q["room"], c["no_conflict"]
            strong, minimal = _pair("q.break", q["break"])
            trend_all, trend_one = _pair("c.htf_trend", c["htf_trend"])
            cfg = cls(
                scoring_version=str(w["scoring_version"]),
                q_permille=_int("q_permille", w["q_permille"]),
                c_permille=_int("c_permille", w["c_permille"]),
                high_quality=_int("high_quality", w["high_quality"]),
                break_strong=strong, break_minimal=minimal,
                sweep=_int("q.sweep", q["sweep"]), fvg=_int("q.fvg", q["fvg"]),
                ob_fresh=_int("q.ob_fresh", q["ob_fresh"]),
                room_full_m=_int("q.room.full_m", room["full_m"]),
                room_full=_int("q.room.full", room["full"]),
                room_part_m=_int("q.room.part_m", room["part_m"]),
                room_part=_int("q.room.part", room["part"]),
                spread_session=_int("q.spread_session", q["spread_session"]),
                trend_all=trend_all, trend_one=trend_one,
                htf_zone=_int("c.htf_zone", c["htf_zone"]),
                ltf_confirm=_int("c.ltf_confirm", c["ltf_confirm"]),
                no_conflict=_int("c.no_conflict.points", conflict["points"]),
                conflict_distance_m=_int("c.no_conflict.distance_m", conflict["distance_m"]),
            )  # fmt: skip
        except (KeyError, TypeError) as exc:
            raise ScoringConfigError(f"weights: missing or malformed key {exc}") from exc
        cfg.check()
        return cfg

    def check(self) -> None:
        """Raise ScoringConfigError unless the weights are consistent."""
        if self.q_permille + self.c_permille != PERMILLE:
            raise ScoringConfigError("q_permille + c_permille must be 1000 permille")
        q_max = (self.break_strong + self.sweep + self.fvg + self.ob_fresh + self.room_full
                 + self.spread_session)  # fmt: skip
        c_max = self.trend_all + self.htf_zone + self.ltf_confirm + self.no_conflict
        if q_max != SCORE_MAX:
            raise ScoringConfigError(f"Q factor maxima must sum to 100, got {q_max}")
        if c_max != SCORE_MAX:
            raise ScoringConfigError(f"C factor maxima must sum to 100, got {c_max}")


@dataclass(frozen=True, slots=True)
class Factor:
    """One scored factor: ``code`` belongs to exactly one score (Q or C; FR-MTF-03, 04)."""

    code: str
    score: Score
    points: int
    max: int
    reason: str
    args: Args = ()

    def arg(self, name: str) -> Any:  # noqa: ANN401 - template values are str, int or tuples
        """A template value."""
        return dict(self.args)[name]

    def to_json(self) -> dict[str, Any]:
        """``{code, score, points, max, reason}`` as stored in ``setups.factors`` (DD 2.5)."""
        return {"code": self.code, "score": self.score, "points": self.points, "max": self.max,
                "reason": self.reason}  # fmt: skip


Reason = Literal["created", "ltf_confirmation", "zone_invalidated", "zone_expired"]


@dataclass(frozen=True, slots=True)
class Revision:
    """A ``setup_revisions`` row: the score and status after one change."""

    rev: int
    q: int
    c: int
    combined: int
    status: str
    factors: tuple[Factor, ...]
    reason: Reason
    effective_time: datetime


@dataclass(frozen=True, slots=True)
class Setup:
    """A scored setup; its columns always equal its latest revision (DD 2.5)."""

    candidate: SetupCandidate
    scoring_version: str
    price_scale: int
    q: int
    c: int
    combined: int
    high_quality: bool
    counter_trend: bool
    factors: tuple[Factor, ...]
    status: str
    status_time: datetime
    revision: int
    ltf_confirmed_at: datetime | None
    revisions: tuple[Revision, ...]
    explanation: str = ""

    @property
    def id(self) -> str:
        """Setup ID (DD 3.8)."""
        return self.candidate.id

    @property
    def direction(self) -> str:
        """``bull`` or ``bear``."""
        return self.candidate.direction

    @property
    def primary_zone_id(self) -> str:
        """The OB, else the FVG (``setups.primary_zone_id``)."""
        zid = self.candidate.ob_zone_id or self.candidate.fvg_zone_id
        if zid is None:  # a candidate always has one (DB check); keeps the type exact
            raise ValueError("setup without a zone")
        return zid
