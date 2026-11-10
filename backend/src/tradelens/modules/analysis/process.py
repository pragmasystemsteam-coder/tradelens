"""Candle-close processing: step new candles of one instrument through the engine (task 1.9).

For each instrument whose data is ``ok``: load the saved state of every timeframe, load the
stored candles that closed after it, step them with ``tradelens_engine.multi.step_batch``
(merged by close time, highest timeframe first) and hand the whole batch to the store, which
writes events, zones, transitions, levels and states in one transaction. A delayed series is
never stepped (DD 8.1 review focus 1); its candles are stepped in order once it resumes.

A missing or unreadable state (first start, a new state layout) is rebuilt from every stored
candle (so levels and zones from older history are replayed, never left open); deterministic
IDs and insert-only writes make the rebuild harmless (FR-SMC-11). Derived candles (15m-1D) are
built in the same ingest pass as the 5m candles they come from, so a close batch sees them
together (review note: a derived candle stored a pass late would be stepped late).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from tradelens.modules.market_data.public import SeriesStatus, StoredCandle
from tradelens_engine.multi import BatchResult, step_batch
from tradelens_engine.series import SeriesState
from tradelens_engine.settings import Settings
from tradelens_engine.types import Candle

TIMEFRAMES = ("5m", "15m", "1h", "4h", "1d")
STATUS_TIMEFRAME = "5m"  # ingest writes one status for all five series of an instrument
OK = "ok"
TINY = timedelta(microseconds=1)

log = logging.getLogger("tradelens.analysis.process")


class CandleSource(Protocol):
    """Stored candles and series status (``market_data.SqlCandleStore`` in production)."""

    def load(self, instrument: str, timeframe: str, since: datetime | None) -> list[StoredCandle]:
        """Stored candles from ``since`` (all when None), ascending."""
        ...

    def get_status(self, instrument: str, timeframe: str) -> SeriesStatus | None:
        """The series_status row."""
        ...


@dataclass(frozen=True, slots=True)
class CloseBatch:
    """What one instrument's close batch produced (saved as one transaction)."""

    instrument: str
    settings_hash: str
    rule_version: str
    result: BatchResult

    @property
    def steps(self) -> tuple[tuple[str, datetime], ...]:
        """``(timeframe, close_time)`` of every candle stepped, in order."""
        return self.result.steps

    def last_close(self) -> dict[str, datetime]:
        """Timeframe to the close time of its newest stepped candle."""
        return dict(self.result.steps)  # later steps of a timeframe win


class AnalysisStore(Protocol):
    """Engine state and output persistence (``SqlAnalysisStore`` in production)."""

    def load_state(
        self, instrument: str, timeframe: str, settings_hash: str
    ) -> Mapping[str, Any] | None:
        """The saved state JSON, or None."""
        ...

    def save_batch(self, batch: CloseBatch) -> None:
        """Write everything in ``batch`` inside the caller's transaction."""
        ...


def to_engine(candle: StoredCandle) -> Candle:
    """A stored candle as an engine candle (spread from the bid and ask closes)."""
    return Candle(candle.open_time, candle.close_time, candle.o, candle.h, candle.l, candle.c,
                  candle.bid_c, candle.ask_c)  # fmt: skip


class CloseProcessor:
    """Steps closed candles for the official settings of one rule version."""

    def __init__(self, cfg: Settings, rule_version: str) -> None:
        self.cfg = cfg
        self.rule_version = rule_version
        self.settings_hash = cfg.hash(rule_version)

    def _state(self, store: AnalysisStore, instrument: str, tf: str) -> SeriesState | None:
        raw = store.load_state(instrument, tf, self.settings_hash)
        if raw is None:
            return None
        try:
            return SeriesState.from_json(dict(raw))
        except (ValueError, KeyError, TypeError) as exc:
            log.warning("series state unreadable; rebuilding from candles",
                        extra={"instrument": instrument, "timeframe": tf,
                               "error": type(exc).__name__})  # fmt: skip
            return None

    def _pending(
        self, candles: CandleSource, instrument: str, tf: str, state: SeriesState | None,
        now: datetime,
    ) -> Sequence[Candle]:  # fmt: skip
        since = None if state is None or state.last_open_time is None else state.last_open_time
        rows = candles.load(instrument, tf, None if since is None else since + TINY)
        return [to_engine(r) for r in rows if r.close_time <= now]

    def process(
        self, candles: CandleSource, store: AnalysisStore, instrument: str, now: datetime
    ) -> CloseBatch | None:
        """Step and save the new candles of ``instrument``.

        Args:
            candles: Stored candles and status, in the caller's transaction.
            store: Engine output store, in the same transaction.
            instrument: Instrument code.
            now: Batch time from the injected clock (only candles closed by then are used).

        Returns:
            The saved batch, or None when the series is not ``ok`` (delayed: never stepped)
            or nothing new closed.
        """
        status = candles.get_status(instrument, STATUS_TIMEFRAME)
        if status is None or status.status != OK:
            return None
        states: dict[str, SeriesState] = {}
        series: dict[str, Sequence[Candle]] = {}
        for tf in TIMEFRAMES:
            state = self._state(store, instrument, tf)
            if state is not None:
                states[tf] = state
            series[tf] = self._pending(candles, instrument, tf, state, now)
        if any(tf not in states and series[tf] for tf in TIMEFRAMES) and states:
            # One timeframe must be rebuilt: rebuild all of them, so the rebuilt series never
            # sees a higher-timeframe state from after its candles (no look-ahead, FR-MTF-02).
            log.warning("rebuilding every series state", extra={"instrument": instrument})
            states = {}
            series = {tf: self._pending(candles, instrument, tf, None, now) for tf in TIMEFRAMES}
        result = step_batch(states, series, self.cfg, instrument=instrument,
                            rule_version=self.rule_version)  # fmt: skip
        if not result.steps:
            return None
        batch = CloseBatch(instrument, self.settings_hash, self.rule_version, result)
        store.save_batch(batch)
        return batch
