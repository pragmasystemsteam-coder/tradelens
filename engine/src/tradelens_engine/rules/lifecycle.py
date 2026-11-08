"""Zone lifecycle for order blocks and FVGs (FR-ZONE-01..05; DD 3.4 "Zone lifecycle").

Bull (demand) zone: touched ``c.l <= high``; 50% mitigated ``c.l * 2 <= low + high``; filled
``c.l < low`` (wick through the far edge); invalidated ``c.c < low`` (close beyond it). Bear
(supply) mirrors with highs. States only move forward and one candle's transitions share its
close. A retest is counted when a candle overlaps the zone after the previous candle did not.
A zone expires when its age exceeds ``zone_max_age`` (the 101st candle) or its retests exceed
``zone_max_retests`` (the 4th); invalidation on the same candle wins.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Literal

from tradelens_engine.events import Zone
from tradelens_engine.types import Candle

ZoneStateName = Literal["confirmed", "touched", "mitigated_50", "filled", "invalidated", "expired"]
RANK: dict[str, int] = {
    "confirmed": 0, "touched": 1, "mitigated_50": 2, "filled": 3, "invalidated": 4, "expired": 4,
}  # fmt: skip
ACTIVE_STATES = frozenset({"confirmed", "touched", "mitigated_50", "filled"})


@dataclass(frozen=True, slots=True)
class ZoneState:
    """An active zone and its lifecycle counters; ``created_bar`` is the bar it was confirmed."""

    zone: Zone
    state: ZoneStateName
    state_time: datetime
    created_bar: int
    retests: int = 0
    prev_overlap: bool = False


def advance_zone(zs: ZoneState, candle: Candle) -> tuple[ZoneState, tuple[ZoneStateName, ...]]:
    """Apply one candle to a zone that existed before it (step 9 of DD 3.4).

    Returns:
        The new zone state and the states entered, in order.
    """
    if zs.state not in ACTIVE_STATES:
        return zs, ()
    z, c = zs.zone, candle
    inside = c.l <= z.high and c.h >= z.low
    retests = zs.retests + (1 if inside and not zs.prev_overlap else 0)
    reached: tuple[tuple[ZoneStateName, bool], ...]
    if z.direction == "bull":
        reached = (
            ("touched", c.l <= z.high),
            ("mitigated_50", c.l * 2 <= z.low + z.high),
            ("filled", c.l < z.low),
            ("invalidated", c.c < z.low),
        )
    else:
        reached = (
            ("touched", c.h >= z.low),
            ("mitigated_50", c.h * 2 >= z.low + z.high),
            ("filled", c.h > z.high),
            ("invalidated", c.c > z.high),
        )
    moves = tuple(name for name, ok in reached if ok and RANK[name] > RANK[zs.state])
    if moves:
        zs = replace(zs, state=moves[-1], state_time=c.close_time)
    return replace(zs, retests=retests, prev_overlap=inside), moves


def expire_zone(
    zs: ZoneState, bar: int, max_age: int, max_retests: int, at: datetime
) -> tuple[ZoneState, bool]:
    """Expire an active zone that is too old or retested too often (step 10 of DD 3.4)."""
    if zs.state not in ACTIVE_STATES:
        return zs, False
    if bar - zs.created_bar > max_age or zs.retests > max_retests:
        return replace(zs, state="expired", state_time=at), True
    return zs, False
