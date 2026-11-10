"""Setup candidates (DD 3.6; FR-SCAN-01, FR-MTF-01).

A candidate is created when an internal BOS or CHoCH confirms on 15m, 1H or 4H, a
same-direction displacement ended within the last ``disp_break_window`` candles (the break
candle included), and an OB or FVG exists in the move. Patterns: the break type,
``displacement``, then ``sweep``, ``fvg`` and ``ob`` when present. Scoring (Q and C factors)
is task 2.x; the candidate carries every input it needs, including the higher-timeframe
context as of the break close.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from tradelens_engine.context import HigherTfContext


@dataclass(frozen=True, slots=True)
class SetupCandidate:
    """Everything the scorer needs about one break (IDs per DD 3.8)."""

    id: str
    instrument: str
    timeframe: str
    profile: str
    direction: str
    break_event_id: str
    break_type: str
    patterns: tuple[str, ...]
    sessions: tuple[str, ...]
    spread: int
    atr_k: int | None
    displacement_event_id: str
    displacement_strong: bool
    sweep_event_id: str | None
    ob_zone_id: str | None
    fvg_zone_id: str | None
    ob_pre_touched: bool
    invalidation: int
    opposing_level: int | None
    origin_time: datetime
    confirm_time: datetime
    settings_hash: str
    rule_version: str
    context: HigherTfContext | None
    zone_low: int  # primary zone (OB, else FVG) bounds: room to liquidity uses the near edge
    zone_high: int
    break_level: int  # the broken swing price (explanations)
    displacement_candles: int
