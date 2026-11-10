"""Development chart payload: candles plus engine overlays (DD 8.1 task 1.10; demo only).

Runs the engine over the stored candles of one series (all of them, so swings and ATR are warm)
and returns the last ``show`` candles with the overlays that touch them: swings, BOS/CHoCH,
sweeps and breakouts as markers; FVG and order-block boxes from confirmation to their end
state; liquidity levels from confirmation to their end. Prices stay integers (smallest units)
with ``price_scale``; the page divides for display only.

The customer chart (task 2.6) replaces this with the cached ``/charts`` endpoint.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from tradelens.core.db import get_engine
from tradelens.modules.analysis.process import to_engine
from tradelens.modules.analysis.service import load_active_rule
from tradelens.modules.market_data.public import (
    SqlCandleStore,
    StoredCandle,
    load_instrument_specs,
)
from tradelens_engine.run import run
from tradelens_engine.settings import Settings

MARKER_TYPES = ("swing_high", "swing_low", "bos", "choch", "sweep", "breakout")
END_STATES = ("filled", "invalidated", "expired")
DEFAULT_SHOW = 500


def _ts(t: datetime) -> int:
    return int(t.timestamp())


def chart_payload(
    rows: Sequence[StoredCandle],
    instrument: str,
    timeframe: str,
    cfg: Settings,
    rule_version: str,
    *,
    price_scale: int,
    show: int = DEFAULT_SHOW,
) -> dict[str, Any]:
    """Engine output for one series, shaped for Lightweight Charts.

    Args:
        rows: Stored candles of the series, oldest first.
        instrument: Instrument code.
        timeframe: Series timeframe.
        cfg: Settings to run (the official rule version's).
        rule_version: Rule version (part of IDs).
        price_scale: Decimal places for display.
        show: How many of the newest candles to return.

    Returns:
        ``{instrument, timeframe, price_scale, candles, markers, zones, levels}``; times are
        Unix seconds of the candle open (markers sit on the confirming candle).
    """
    candles = [to_engine(r) for r in rows]
    result = run(candles, cfg, instrument=instrument, timeframe=timeframe,
                 rule_version=rule_version)  # fmt: skip
    shown = candles[-show:] if show > 0 else []
    if not shown:
        return {"instrument": instrument, "timeframe": timeframe, "price_scale": price_scale,
                "candles": [], "markers": [], "zones": [], "levels": []}  # fmt: skip
    start, last = shown[0].open_time, shown[-1].open_time
    open_of = {c.close_time: c.open_time for c in candles}
    markers = [
        {"time": _ts(open_of[e.confirm_time]), "kind": e.type, "structure": e.structure,
         "direction": e.direction, "level": e.level}
        for e in result.events
        if e.type in MARKER_TYPES and open_of.get(e.confirm_time, start) >= start
    ]  # fmt: skip
    ends: dict[str, datetime] = {}
    for zid, state, t in result.zone_transitions:
        if state in END_STATES and zid not in ends:
            ends[zid] = t
    zones = []
    for z in result.zones:
        end = ends.get(z.id, shown[-1].close_time)
        if end < start or z.confirm_time > shown[-1].close_time:
            continue
        zones.append({"id": z.id, "kind": z.kind, "direction": z.direction, "low": z.low,
                      "high": z.high, "start": _ts(max(open_of.get(z.confirm_time, start), start)),
                      "end": _ts(min(open_of.get(end, last), last))})  # fmt: skip
    levels: dict[str, dict[str, Any]] = {}
    for ch in result.level_changes:
        lv = ch.level
        levels[lv.id] = {"id": lv.id, "kinds": list(lv.kinds), "side": lv.side, "price": lv.price,
                         "confirm": lv.confirm_time, "end": lv.end_time,
                         "end_reason": lv.end_reason}  # fmt: skip
    for lv_state in result.state.levels:  # still active at the end
        levels.setdefault(lv_state.id, {"id": lv_state.id, "kinds": list(lv_state.kinds),
                                         "side": lv_state.side, "price": lv_state.price,
                                         "confirm": lv_state.confirm_time, "end": None,
                                         "end_reason": None})  # fmt: skip
    lines = []
    for row in levels.values():
        end = row["end"] or shown[-1].close_time
        if end < start:
            continue
        lines.append({**{k: row[k] for k in ("id", "kinds", "side", "price", "end_reason")},
                      "start": _ts(max(open_of.get(row["confirm"], start), start)),
                      "end": _ts(min(open_of.get(end, last), last))})  # fmt: skip
    return {
        "instrument": instrument, "timeframe": timeframe, "price_scale": price_scale,
        "candles": [{"time": _ts(c.open_time), "open": c.o, "high": c.h, "low": c.l,
                     "close": c.c} for c in shown],
        "markers": markers, "zones": zones, "levels": lines,
    }  # fmt: skip


class SqlChartSource:
    """Dev chart data from the database: stored candles and the active rule version."""

    def __init__(self, database_url: str, config_dir: Path) -> None:
        self._url = database_url
        self._config_dir = config_dir
        self._scales: dict[str, int] | None = None  # read on first use, not at app start
        self._rule: tuple[Settings, str] | None = None

    def _active(self) -> tuple[Settings, str]:
        if self._rule is None:
            with get_engine(self._url).connect() as conn:
                rule = load_active_rule(conn)
            self._rule = (rule.settings, rule.version)
        return self._rule

    @property
    def settings(self) -> Settings:
        """Settings of the active rule version."""
        return self._active()[0]

    @property
    def rule_version(self) -> str:
        """The active rule version."""
        return self._active()[1]

    def candles(self, instrument: str, timeframe: str) -> Sequence[StoredCandle]:
        """Every stored candle of the series, oldest first."""
        with get_engine(self._url).connect() as conn:
            return SqlCandleStore(conn).load(instrument, timeframe, None)

    def price_scale(self, instrument: str) -> int | None:
        """Decimal places from config/instruments.json."""
        if self._scales is None:
            specs = load_instrument_specs(self._config_dir)
            self._scales = {s.code: s.price_scale for s in specs}
        return self._scales.get(instrument)
