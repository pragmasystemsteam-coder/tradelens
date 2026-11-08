"""``run``: repeated ``step`` over a candle list, so batch and live never drift (NFR-07)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

from tradelens_engine.events import Event, Zone
from tradelens_engine.rules.liquidity import LevelChange
from tradelens_engine.series import SeriesState
from tradelens_engine.settings import Settings
from tradelens_engine.setups import SetupCandidate
from tradelens_engine.step import StepOutput, step
from tradelens_engine.types import Candle


@dataclass(frozen=True, slots=True)
class EngineResult:
    """Everything ``run`` produced, in emission order, plus the final state."""

    events: tuple[Event, ...]
    zones: tuple[Zone, ...]
    zone_transitions: tuple[tuple[str, str, datetime], ...]
    state: SeriesState
    level_changes: tuple[LevelChange, ...] = ()
    setup_candidates: tuple[SetupCandidate, ...] = ()


@dataclass(slots=True)
class Collector:
    """Accumulates step outputs of one series into an :class:`EngineResult`."""

    state: SeriesState
    outputs: list[StepOutput] = field(default_factory=list)

    def add(self, state: SeriesState, out: StepOutput) -> None:
        """Record one step."""
        self.state = state
        self.outputs.append(out)

    def result(self) -> EngineResult:
        """Everything collected so far."""
        outs = self.outputs
        return EngineResult(
            tuple(e for o in outs for e in o.events),
            tuple(z for o in outs for z in o.new_zones),
            tuple(t for o in outs for t in o.zone_transitions),
            self.state,
            tuple(c for o in outs for c in o.level_changes),
            tuple(s for o in outs for s in o.setup_candidates),
        )


def run(
    candles: Iterable[Candle],
    cfg: Settings,
    *,
    instrument: str,
    timeframe: str,
    rule_version: str,
    state: SeriesState | None = None,
) -> EngineResult:
    """Step every candle in order from ``state`` (default: empty), without HTF context.

    Raises:
        OutOfOrderCandle: If open times are not strictly increasing.
    """
    acc = Collector(state if state is not None else SeriesState())
    for candle in candles:
        acc.add(*step(acc.state, candle, cfg, instrument=instrument, timeframe=timeframe,
                      rule_version=rule_version))  # fmt: skip
    return acc.result()
