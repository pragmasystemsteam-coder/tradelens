"""Combined rank and the scored setup at creation (DD 3.6; FR-MTF-05, 06, 07).

Combined = (q_permille x Q + c_permille x C + 500) // 1000 (600/400 in s1.0), rounded half up;
high quality = combined >= ``high_quality`` (60). Q and the first three C factors are frozen at
creation; re-evaluation only adds the lower-timeframe confirmation and changes the status.
"""

from __future__ import annotations

from dataclasses import replace

from tradelens_engine.arith import combined_score
from tradelens_engine.scoring.confluence import c_factors
from tradelens_engine.scoring.explain import explain
from tradelens_engine.scoring.model import Factor, Revision, ScoringConfig, Setup
from tradelens_engine.scoring.quality import q_factors
from tradelens_engine.setups import SetupCandidate

COUNTER_TREND_HIDE = "hide"


def combined(q: int, c: int, w: ScoringConfig) -> int:
    """Combined rank from Q and C with the version's weights (half up, integers only)."""
    return combined_score(q, c, w.q_permille, w.c_permille)


def high_quality(combined_value: int, w: ScoringConfig) -> bool:
    """FR-MTF-07: 60 is high quality, 59 is not (threshold from the weights)."""
    return combined_value >= w.high_quality


def totals(factors: tuple[Factor, ...]) -> tuple[int, int]:
    """``(Q, C)`` as the sums of their factors' points."""
    q = sum(f.points for f in factors if f.score == "Q")
    c = sum(f.points for f in factors if f.score == "C")
    return q, c


def with_factors(setup: Setup, factors: tuple[Factor, ...], w: ScoringConfig) -> Setup:
    """The setup with new factors and the scores and explanation that follow from them."""
    q, c = totals(factors)
    value = combined(q, c, w)
    s = replace(setup, factors=factors, q=q, c=c, combined=value,
                high_quality=high_quality(value, w))  # fmt: skip
    return replace(s, explanation=explain(s))


def score_candidate(
    cand: SetupCandidate,
    w: ScoringConfig,
    *,
    normal_spread: int,
    price_scale: int,
    counter_trend: str = "warn",
) -> Setup | None:
    """Score a candidate at its break close: revision 1 (DD 3.1 ``score_candidate``).

    Args:
        cand: The candidate, with its higher-timeframe context as of the break close.
        w: Weights of the active scoring version.
        normal_spread: The instrument's normal spread in smallest units.
        price_scale: Decimal places of the instrument (explanations only).
        counter_trend: ``warn`` keeps counter-trend setups with a badge; ``hide`` drops them
            (custom settings, FR-MTF-06).

    Returns:
        The setup, or None when it is counter-trend and ``counter_trend`` is ``hide``.
    """
    qf = q_factors(cand, w, normal_spread)
    cf, counter = c_factors(cand, w)
    if counter and counter_trend == COUNTER_TREND_HIDE:
        return None
    factors = (*qf, *cf)
    q, c = totals(factors)
    value = combined(q, c, w)
    first = Revision(1, q, c, value, "confirmed", factors, "created", cand.confirm_time)
    setup = Setup(
        candidate=cand, scoring_version=w.scoring_version, price_scale=price_scale, q=q, c=c,
        combined=value, high_quality=high_quality(value, w), counter_trend=counter,
        factors=factors, status="confirmed", status_time=cand.confirm_time, revision=1,
        ltf_confirmed_at=None, revisions=(first,),
    )  # fmt: skip
    return replace(setup, explanation=explain(setup))
