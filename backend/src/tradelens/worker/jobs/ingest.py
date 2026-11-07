"""Ingest job: one pass over every instrument, one transaction per instrument (FR-DATA-02)."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

from tradelens.modules.market_data.public import IngestService, InstrumentReport, SqlCandleStore
from tradelens.worker.scheduler import next_run_at

log = logging.getLogger("tradelens.worker.ingest")


def run_ingest_once(
    engine: Engine, service: IngestService, clock: Callable[[], datetime]
) -> list[InstrumentReport]:
    """Ingest every instrument; a failure of one instrument never stops the others.

    The connection runs in AUTOCOMMIT: provider calls can wait up to a minute for the credit
    limiter, so no transaction (and no lock) is held open across them. Every write is
    idempotent (candles never overwrite, statuses are upserts), so a pass that stops halfway
    is completed by the next one.

    Args:
        engine: SQLAlchemy engine (application role).
        service: Configured ingest service.
        clock: UTC clock.

    Returns:
        One report per instrument.
    """
    reports = []
    for code in service.instruments:
        try:
            with engine.connect() as conn:
                conn = conn.execution_options(isolation_level="AUTOCOMMIT")
                reports.append(service.ingest_instrument(SqlCandleStore(conn), code, clock()))
        except Exception as exc:
            log.exception("ingest failed", extra={"instrument": code})
            reports.append(_mark_failed(engine, service, code, clock(), type(exc).__name__))
    delayed = [r.instrument for r in reports if r.status != "ok"]
    log.info("ingest pass done", extra={"instruments": len(reports), "delayed": delayed})
    return reports


def _mark_failed(
    engine: Engine, service: IngestService, code: str, now: datetime, reason: str
) -> InstrumentReport:
    """Record "Data delayed" for an instrument whose pass failed; never raises."""
    try:
        with engine.begin() as conn:
            return service.mark_failed(SqlCandleStore(conn), code, now, reason)
    except SQLAlchemyError:
        log.exception("could not mark series delayed", extra={"instrument": code})
        return InstrumentReport(code, status="delayed", errors=[reason])


def run_ingest_loop(
    engine: Engine,
    service: IngestService,
    clock: Callable[[], datetime],
    stop: threading.Event,
    offset_s: int,
) -> None:
    """Run an ingest pass now, then at every 5-minute boundary + offset until ``stop``."""
    while not stop.is_set():
        try:
            run_ingest_once(engine, service, clock)
        except Exception:
            log.exception("ingest pass crashed; retrying at the next boundary")
        wait = (next_run_at(clock(), offset_s=offset_s) - clock()).total_seconds()
        stop.wait(max(wait, 0.0))
