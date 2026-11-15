"""Batch-end re-evaluation of confirmed setups (DD 3.6; FR-MTF-04, FR-ZONE-05).

Only what is known as of the batch close (``as_of``) counts; the wall clock is never read, so
replaying the same rows gives the same revisions.

* Lower-timeframe confirmation (once): after the primary zone is first touched (touched,
  mitigated_50 or filled after the setup confirmed), the first same-direction internal BOS or
  CHoCH on a confirmation timeframe that confirms after the touching candle's open adds the
  ``ltf_confirm`` points to C and writes revision ``ltf_confirmation``.
* Status: when the primary zone (OB, else FVG) is invalidated or expires, the setup becomes
  invalidated or expired (revision ``zone_invalidated`` / ``zone_expired``). Filled changes nothing.

Changes are applied in time order, so one batch can confirm and then invalidate a setup.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime, timedelta

from tradelens_engine.events import Event
from tradelens_engine.scoring.model import Factor, Reason, Revision, ScoringConfig, Setup
from tradelens_engine.scoring.rank import with_factors
from tradelens_engine.types import TIMEFRAME_MINUTES

CONFIRM_TFS: dict[str, tuple[str, ...]] = {
    "scalping": ("5m",), "intraday": ("15m", "5m"), "swing": ("1h",),
}  # fmt: skip
TOUCH_STATES = ("touched", "mitigated_50", "filled")
END_STATES: dict[str, tuple[str, Reason]] = {
    "invalidated": ("invalidated", "zone_invalidated"),
    "expired": ("expired", "zone_expired"),
}
Transition = tuple[str, str, datetime]


def _ltf_event(
    s: Setup, transitions: Sequence[Transition], events: Sequence[Event], as_of: datetime
) -> Event | None:
    c = s.candidate
    touches = sorted(t for zid, state, t in transitions
                     if zid == s.primary_zone_id and state in TOUCH_STATES
                     and c.confirm_time < t <= as_of)  # fmt: skip
    if not touches:
        return None
    touch_open = touches[0] - timedelta(minutes=TIMEFRAME_MINUTES[c.timeframe])
    found = sorted(
        (e for e in events
         if e.type in ("bos", "choch") and e.structure == "internal"
         and e.direction == c.direction and e.timeframe in CONFIRM_TFS[c.profile]
         and touch_open < e.confirm_time <= as_of),
        key=lambda e: (e.confirm_time, e.id),
    )  # fmt: skip
    return found[0] if found else None


def _end(
    s: Setup, transitions: Sequence[Transition], as_of: datetime
) -> tuple[str, datetime] | None:
    ends = sorted((t, state) for zid, state, t in transitions
                  if zid == s.primary_zone_id and state in END_STATES
                  and s.candidate.confirm_time < t <= as_of)  # fmt: skip
    return None if not ends else (ends[0][1], ends[0][0])


def _revise(s: Setup, reason: Reason, at: datetime) -> Setup:
    rev = Revision(s.revision + 1, s.q, s.c, s.combined, s.status, s.factors, reason, at)
    return replace(s, revision=rev.rev, revisions=(*s.revisions, rev))


def reevaluate(
    setup: Setup,
    transitions: Sequence[Transition],
    confirm_events: Sequence[Event],
    as_of: datetime,
    w: ScoringConfig,
) -> Setup | None:
    """Apply what happened up to ``as_of`` to a confirmed setup.

    Args:
        setup: The setup as last saved.
        transitions: ``(zone_id, state, candle_close)`` of its zones (others are ignored).
        confirm_events: Events of the confirmation timeframes (others are ignored).
        as_of: Close time of the batch; nothing later is used.
        w: Weights of the setup's scoring version.

    Returns:
        The setup with one or two new revisions, or None when nothing changed.
    """
    if setup.status != "confirmed":
        return None
    s = setup
    end = _end(s, transitions, as_of)
    if s.ltf_confirmed_at is None:
        event = _ltf_event(s, transitions, confirm_events, as_of)
        if event is not None and (end is None or event.confirm_time < end[1]):
            ltf = Factor("ltf_confirm", "C", w.ltf_confirm, w.ltf_confirm, "confirmed",
                         (("tf", event.timeframe), ("break_type", event.type)))  # fmt: skip
            factors = tuple(ltf if f.code == "ltf_confirm" else f for f in s.factors)
            s = with_factors(replace(s, ltf_confirmed_at=event.confirm_time), factors, w)
            s = _revise(s, "ltf_confirmation", event.confirm_time)
    if end is not None:
        status, reason = END_STATES[end[0]]
        s = _revise(replace(s, status=status, status_time=end[1]), reason, end[1])
    return None if s is setup else s
