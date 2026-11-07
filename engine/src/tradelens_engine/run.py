"""``run``: repeated ``step`` over a candle list, so batch and live never drift (NFR-07)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from tradelens_engine.events import Event, Zone
from tradelens_engine.series import SeriesState
from tradelens_engine.settings import Settings
from tradelens_engine.step import step
from tradelens_engine.types import Candle


@dataclass(frozen=True, slots=True)
class EngineResult:
    """Everything ``run`` produced, in emission order, plus the final state."""

    events: tuple[Event, ...]
    zones: tuple[Zone, ...]
    zone_transitions: tuple[tuple[str, str, datetime], ...]
    state: SeriesState


def run(
    candles: Iterable[Candle],
    cfg: Settings,
    *,
    instrument: str,
    timeframe: str,
    rule_version: str,
    state: SeriesState | None = None,
) -> EngineResult:
    """Step every candle in order from ``state`` (default: empty).

    Raises:
        OutOfOrderCandle: If open times are not strictly increasing.
    """
    current = state if state is not None else SeriesState()
    events: list[Event] = []
    zones: list[Zone] = []
    transitions: list[tuple[str, str, datetime]] = []
    for candle in candles:
        current, out = step(
            current, candle, cfg, instrument=instrument, timeframe=timeframe,
            rule_version=rule_version,
        )  # fmt: skip
        events.extend(out.events)
        zones.extend(out.new_zones)
        transitions.extend(out.zone_transitions)
    return EngineResult(tuple(events), tuple(zones), tuple(transitions), current)
