"""Higher-timeframe context for setups (DD 3.5; FR-MTF-02).

A context is built from the saved states of the profile's context timeframes: internal trend,
ATR and active zones as of their last closed candle, so a forming candle is never visible.
A context with fewer than ``atr_period`` (14) candles is not ready (it scores 0 later).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from tradelens_engine.rules.lifecycle import ACTIVE_STATES
from tradelens_engine.series import SeriesState

PROFILE_BY_TF: dict[str, str] = {"15m": "scalping", "1h": "intraday", "4h": "swing"}
CONTEXT_TFS: dict[str, tuple[str, ...]] = {
    "scalping": ("1h",), "intraday": ("1d", "4h"), "swing": ("1d",),
}  # fmt: skip


@dataclass(frozen=True, slots=True)
class ContextZone:
    """An active zone of a context timeframe."""

    id: str
    kind: str
    direction: str
    low: int
    high: int
    state: str


@dataclass(frozen=True, slots=True)
class TfContext:
    """One context timeframe as of its last closed candle (``as_of``)."""

    timeframe: str
    ready: bool
    trend: str
    atr_k: int | None
    as_of: datetime | None
    zones: tuple[ContextZone, ...]


@dataclass(frozen=True, slots=True)
class HigherTfContext:
    """The context of one setup profile (contexts in the profile's order)."""

    profile: str
    contexts: tuple[TfContext, ...]


def build_context(states_by_tf: Mapping[str, SeriesState], profile: str) -> HigherTfContext:
    """Context for ``profile`` from the latest saved states (DD 3.5).

    Args:
        states_by_tf: Timeframe to the state after its last closed candle (missing = empty).
        profile: ``scalping``, ``intraday`` or ``swing``.

    Returns:
        The context; a timeframe without an ATR yet is ``ready=False`` with no trend or zones.
    """
    contexts = []
    for tf in CONTEXT_TFS[profile]:
        st = states_by_tf.get(tf)
        if st is None or st.atr.atr_k is None:
            as_of = None if st is None else st.last_close_time
            contexts.append(TfContext(tf, False, "neutral", None, as_of, ()))
            continue
        zones = tuple(
            ContextZone(z.zone.id, z.zone.kind, z.zone.direction, z.zone.low, z.zone.high, z.state)
            for z in st.zones
            if z.state in ACTIVE_STATES
        )
        contexts.append(
            TfContext(tf, True, st.internal.trend, st.atr.atr_k, st.last_close_time, zones)
        )
    return HigherTfContext(profile, tuple(contexts))
