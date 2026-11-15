"""Candle-close job: ingest, then engine processing, then live messages (DD 8.1 task 1.9).

Runs every 5-minute boundary + ``SCHEDULER_OFFSET_SECONDS`` (2 s):

1. Ingest every instrument (history once, live 5m, gaps and backfill, derived timeframes,
   ``series_status``); see ``market_data.ingest``.
2. For every instrument whose status is ``ok``: in one transaction, step the candles that
   closed since its saved state (highest timeframe first) and save events, zones, levels and
   states (``analysis.CloseProcessor``). A delayed instrument is never stepped.
3. Publish ``chart.updated`` per stepped timeframe and ``series.delayed`` / ``series.resumed``
   when an instrument's status changed. The whole pass is timed (NFR-01: under 10 s).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import datetime

from tradelens.modules.analysis.public import (
    AnalysisStore,
    CandleSource,
    CloseBatch,
    CloseProcessor,
)
from tradelens.modules.market_data.public import InstrumentReport
from tradelens.worker.publish import Publisher, chart_updated, status_changed
from tradelens.worker.scheduler import next_run_at

log = logging.getLogger("tradelens.worker.close")
Transaction = Callable[[], AbstractContextManager[tuple[CandleSource, AnalysisStore]]]


@dataclass(slots=True)
class CloseReport:
    """One pass: ingest reports, the batch of every instrument stepped, wall time."""

    reports: list[InstrumentReport]
    batches: dict[str, CloseBatch] = field(default_factory=dict)
    failed: list[str] = field(default_factory=list)
    seconds: float = 0.0


class CloseJob:
    """One candle-close pass over every instrument."""

    def __init__(
        self,
        *,
        ingest: Callable[[], list[InstrumentReport]],
        transaction: Transaction,
        processor: CloseProcessor,
        publisher: Publisher,
        clock: Callable[[], datetime],
    ) -> None:
        """Wire the job.

        Args:
            ingest: Runs one ingest pass and returns a report per instrument.
            transaction: Opens one transaction and yields its candle and analysis stores.
            processor: Steps the engine for the active rule version.
            publisher: Redis client used for pub/sub.
            clock: UTC clock (frozen in tests).
        """
        self._ingest = ingest
        self._transaction = transaction
        self._processor = processor
        self._pub = publisher
        self._clock = clock

    def run_once(self) -> CloseReport:
        """Ingest, process and publish; a failing instrument never stops the others."""
        started = time.perf_counter()
        report = CloseReport(self._ingest())
        for rep in report.reports:
            now = self._clock()
            status_changed(self._pub, rep.instrument, rep.status, rep.previous_status, now)
            if rep.status != "ok":
                continue
            try:
                with self._transaction() as (candles, analysis):
                    batch = self._processor.process(candles, analysis, rep.instrument, now)
            except Exception:
                log.exception("close processing failed", extra={"instrument": rep.instrument})
                report.failed.append(rep.instrument)
                continue
            if batch is not None:
                report.batches[rep.instrument] = batch
                chart_updated(self._pub, rep.instrument, batch.last_close())
        report.seconds = time.perf_counter() - started
        log.info("close pass done", extra={
            "seconds": round(report.seconds, 3), "stepped": len(report.batches),
            "steps": sum(len(b.steps) for b in report.batches.values()),
            "delayed": [r.instrument for r in report.reports if r.status != "ok"],
            "failed": report.failed,
        })  # fmt: skip
        return report


def run_close_loop(
    job: CloseJob, clock: Callable[[], datetime], stop: threading.Event, offset_s: int
) -> None:
    """Run a pass now, then at every 5-minute boundary + ``offset_s`` until ``stop``."""
    while not stop.is_set():
        try:
            job.run_once()
        except Exception:
            log.exception("close pass crashed; retrying at the next boundary")
        wait = (next_run_at(clock(), offset_s=offset_s) - clock()).total_seconds()
        stop.wait(max(wait, 0.0))
