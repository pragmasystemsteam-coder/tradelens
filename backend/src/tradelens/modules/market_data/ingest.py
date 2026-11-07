"""Candle ingestion: history once, live 5m, gaps and backfill, derived series.

Implements FR-DATA-02 (complete candles only), FR-DATA-03/05 (history, cached and never
refetched), FR-DATA-09 (calendar-aware gaps, "Data delayed") and CR-004 decisions D2-1..D2-3:

* History for 5m, 15m and 1h is fetched once per series, when nothing is stored yet.
* Afterwards only 5m is fetched (live polling fits the Twelve Data FREE budget); 15m and 1h
  are built from 5m, 4h and 1d from 1h on the 17:00 New York boundary.
* A missing 5m candle with a later candle stored is a gap: it is recorded in ``data_gaps`` and
  backfilled; while it is open, or while the latest candle is overdue, the instrument's series
  are ``delayed``. A gap the provider still cannot fill after ``backfill_window`` is logged and
  stops delaying the series (the provider has no data for it), so it cannot burn credits forever.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

from tradelens.modules.market_data.aggregate import aggregate
from tradelens.modules.market_data.calendar import (
    bucket_open,
    expected_open_times,
    find_gaps,
    is_expected,
)
from tradelens.modules.market_data.candles import (
    StoredCandle,
    complete_bars,
    timeframe_delta,
    to_stored,
)
from tradelens.modules.market_data.ports import (
    BudgetExhaustedError,
    CandleProvider,
    ProviderError,
    RateLimitedError,
    RawBar,
)
from tradelens.modules.market_data.service import InstrumentSpec

HISTORY_TIMEFRAMES = ("5m", "15m", "1h")
LIVE_TIMEFRAME = "5m"
DERIVED = (("5m", "15m"), ("5m", "1h"), ("1h", "4h"), ("1h", "1d"))
ALL_TIMEFRAMES = ("5m", "15m", "1h", "4h", "1d")
MAX_FETCH = 5000
DEFAULT_HISTORY = 2500  # BACKFILL_MIN_CANDLES (DD 2.4)
DEFAULT_GRACE = timedelta(seconds=60)  # CANDLE_RETRY_MAX_SECONDS: a candle this late is overdue
GAP_LOOKBACK = timedelta(days=3)
REBUILD_WINDOW = GAP_LOOKBACK  # derived buckets are rebuilt this far back (late 5m data)
BACKFILL_WINDOW = timedelta(minutes=30)
MAX_BACKFILLS_PER_RUN = 3
TINY = timedelta(microseconds=1)
OK, DELAYED = "ok", "delayed"

log = logging.getLogger("tradelens.market_data.ingest")


@dataclass(frozen=True, slots=True)
class SeriesStatus:
    """A ``series_status`` row."""

    status: str
    last_candle_time: datetime | None
    delayed_since: datetime | None
    checked_at: datetime


@dataclass(slots=True)
class InstrumentReport:
    """What one ingest run did for one instrument."""

    instrument: str
    status: str = OK
    stored: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    halted: bool = False  # a credit or rate limit stopped this pass: no further calls


class CandleStore(Protocol):
    """Persistence used by the ingest job (``repository.SqlCandleStore`` in production)."""

    def last_open_time(self, instrument: str, timeframe: str) -> datetime | None:
        """Open time of the newest stored candle."""
        ...

    def open_times(self, instrument: str, timeframe: str, since: datetime) -> list[datetime]:
        """Open times of stored candles from ``since``, ascending."""
        ...

    def load(self, instrument: str, timeframe: str, since: datetime | None) -> list[StoredCandle]:
        """Stored candles from ``since`` (all when None), ascending."""
        ...

    def add(self, rows: Sequence[StoredCandle]) -> int:
        """Insert candles that are not stored yet; return how many were new."""
        ...

    def get_status(self, instrument: str, timeframe: str) -> SeriesStatus | None:
        """The series_status row."""
        ...

    def set_status(self, instrument: str, timeframe: str, status: SeriesStatus) -> None:
        """Update the series_status row."""
        ...

    def record_gap(
        self, instrument: str, timeframe: str, gap_from: datetime, gap_to: datetime, now: datetime
    ) -> None:
        """Record a gap unless an unfilled gap with the same start exists."""
        ...

    def unfilled_gaps(
        self, instrument: str, timeframe: str, detected_since: datetime | None = None
    ) -> list[tuple[datetime, datetime]]:
        """Unfilled gaps, optionally only those detected since a time."""
        ...

    def fill_gap(self, instrument: str, timeframe: str, gap_from: datetime, now: datetime) -> None:
        """Mark a gap filled."""
        ...


class IngestService:
    """Runs one ingest pass per instrument (called every 5 minutes by the worker)."""

    def __init__(
        self,
        provider: CandleProvider,
        specs: Sequence[InstrumentSpec],
        *,
        history_count: int = DEFAULT_HISTORY,
        grace: timedelta = DEFAULT_GRACE,
        backfill_window: timedelta = BACKFILL_WINDOW,
    ) -> None:
        self._provider = provider
        self._specs = {s.code: s for s in specs}
        self._order = [s.code for s in specs]
        self._history = max(1, min(history_count, MAX_FETCH))
        self._grace = grace
        self._backfill_window = backfill_window

    @property
    def instruments(self) -> list[str]:
        """Instrument codes in config order."""
        return list(self._order)

    def run_once(self, store: CandleStore, now: datetime) -> list[InstrumentReport]:
        """Ingest every instrument with one store (tests; the worker uses one txn each)."""
        return [self.ingest_instrument(store, code, now) for code in self._order]

    def _store(
        self,
        store: CandleStore,
        code: str,
        tf: str,
        bars: Sequence[RawBar],
        now: datetime,
        rep: InstrumentReport,
    ) -> None:
        source = self._provider.source_for(code)
        cal = self._specs[code].calendar
        # Providers may send bars while the market is closed (Twelve Data returns weekend FX
        # bars); only candles the trading calendar expects are stored (FR-DATA-09).
        rows = [
            to_stored(b, code, tf, source)
            for b in complete_bars(bars, tf, now)
            if is_expected(cal, tf, b.open_time)
        ]
        rep.stored[tf] = rep.stored.get(tf, 0) + store.add(rows)

    def _fetch(
        self,
        rep: InstrumentReport,
        what: str,
        code: str,
        tf: str,
        *,
        count: int,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[RawBar] | None:
        if rep.halted:
            return None
        try:
            return self._provider.fetch(code, tf, count=count, start=start, end=end)
        except ProviderError as exc:
            if isinstance(exc, (RateLimitedError, BudgetExhaustedError)):
                rep.halted = True
            rep.errors.append(f"{tf} {what}: {exc}")
            log.warning(
                "candle fetch failed",
                extra={"instrument": code, "timeframe": tf, "what": what, "error": str(exc)},
            )
            return None

    def _history_and_live(
        self, store: CandleStore, code: str, now: datetime, rep: InstrumentReport
    ) -> None:
        for tf in HISTORY_TIMEFRAMES:
            if store.last_open_time(code, tf) is None:
                bars = self._fetch(rep, "history", code, tf, count=self._history)
                if bars is not None:
                    self._store(store, code, tf, bars, now, rep)
        last = store.last_open_time(code, LIVE_TIMEFRAME)
        if last is None:
            return
        step = timeframe_delta(LIVE_TIMEFRAME)
        cal = self._specs[code].calendar
        due = expected_open_times(cal, LIVE_TIMEFRAME, last + step, now - step + TINY)
        if due:
            # Padded: a provider may also send bars the calendar does not expect (weekend FX).
            count = min(2 * len(due) + 2, MAX_FETCH)
            bars = self._fetch(rep, "live", code, LIVE_TIMEFRAME, count=count, start=last + step)
            if bars is not None:
                self._store(store, code, LIVE_TIMEFRAME, bars, now, rep)

    def _gaps(self, store: CandleStore, code: str, now: datetime, rep: InstrumentReport) -> bool:
        """Record and backfill 5m gaps; return True while a recent gap is still open."""
        cal = self._specs[code].calendar
        tf, step = LIVE_TIMEFRAME, timeframe_delta(LIVE_TIMEFRAME)
        for gap_from, gap_to in find_gaps(cal, tf, store.open_times(code, tf, now - GAP_LOOKBACK)):
            store.record_gap(code, tf, gap_from, gap_to, now)
        recent = now - self._backfill_window
        pending = store.unfilled_gaps(code, tf, detected_since=recent)
        for gap_from, gap_to in pending[:MAX_BACKFILLS_PER_RUN]:
            wanted = expected_open_times(cal, tf, gap_from, gap_to)
            bars = self._fetch(
                rep, "backfill", code, tf, count=len(wanted) + 1, start=gap_from, end=gap_to - step
            )
            if bars is not None:
                self._store(store, code, tf, bars, now, rep)
            if set(wanted) <= set(store.open_times(code, tf, gap_from)):
                store.fill_gap(code, tf, gap_from, now)
            else:
                log.warning(
                    "gap still missing after backfill; retried until it is %s old",
                    self._backfill_window,
                    extra={"instrument": code, "gap_from": gap_from.isoformat()},
                )
        return bool(store.unfilled_gaps(code, tf, detected_since=recent))

    def _overdue(self, store: CandleStore, code: str, now: datetime) -> bool:
        """True when the newest 5m candle that should be stored by now is missing."""
        cal = self._specs[code].calendar
        step = timeframe_delta(LIVE_TIMEFRAME)
        must = expected_open_times(
            cal, LIVE_TIMEFRAME, now - GAP_LOOKBACK, now - step - self._grace + TINY
        )
        last = store.last_open_time(code, LIVE_TIMEFRAME)
        return bool(must) and (last is None or last < must[-1])

    def _derive(self, store: CandleStore, code: str, now: datetime, rep: InstrumentReport) -> None:
        cal = self._specs[code].calendar
        for source_tf, target_tf in DERIVED:
            last = store.last_open_time(code, target_tf)
            if last is None and target_tf in HISTORY_TIMEFRAMES:
                continue  # its history has not been fetched yet; never build it from 5m alone
            # Rebuild a recent window, not just after the newest bucket: a bucket that waited
            # for a late or backfilled source candle is built once it is complete. Inserts
            # never overwrite, so rebuilding is idempotent.
            since = None if last is None else bucket_open(target_tf, now - REBUILD_WINDOW)
            built = aggregate(cal, source_tf, target_tf, store.load(code, source_tf, since), now)
            rep.stored[target_tf] = rep.stored.get(target_tf, 0) + store.add(built)

    def _write_status(
        self, store: CandleStore, code: str, now: datetime, rep: InstrumentReport
    ) -> None:
        delayed = rep.status == DELAYED
        for tf in ALL_TIMEFRAMES:
            previous = store.get_status(code, tf)
            since = None
            if delayed:
                kept = previous.delayed_since if previous and previous.status == DELAYED else None
                since = kept or now
            store.set_status(
                code, tf, SeriesStatus(rep.status, store.last_open_time(code, tf), since, now)
            )

    def mark_failed(
        self, store: CandleStore, code: str, now: datetime, reason: str
    ) -> InstrumentReport:
        """Mark all series of ``code`` delayed after an unexpected failure of its pass."""
        rep = InstrumentReport(code, status=DELAYED, errors=[reason])
        self._write_status(store, code, now, rep)
        return rep

    def ingest_instrument(self, store: CandleStore, code: str, now: datetime) -> InstrumentReport:
        """Fetch, store, check and derive one instrument; never raises for provider failures.

        Args:
            store: Candle store (the worker gives it an autocommit connection).
            code: Instrument code.
            now: Current UTC time from the injected clock.

        Returns:
            The report; its status is also written to all five series of the instrument.
        """
        rep = InstrumentReport(code)
        self._history_and_live(store, code, now, rep)
        gap_open = self._gaps(store, code, now, rep)
        self._derive(store, code, now, rep)
        delayed = bool(rep.errors) or gap_open or self._overdue(store, code, now)
        rep.status = DELAYED if delayed else OK
        self._write_status(store, code, now, rep)
        if delayed:
            log.warning("series delayed", extra={"instrument": code, "errors": rep.errors})
        return rep
