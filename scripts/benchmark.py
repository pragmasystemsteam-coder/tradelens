"""Engine benchmark: wall time of one candle-close pass over all 55 series (AD-03; task 1.10).

AD-03: one worker process runs ingestion and the engine; split it only if a close takes over
5 s on the reference server (an ARM VM). This script measures the same ``CloseJob`` the worker
runs, with the fake provider and a frozen clock:

1. warm-up: history (``--history``, default 2,500 candles per fetched series) is ingested and
   stepped once, as on a fresh start (timed separately);
2. ``--closes`` consecutive 5-minute closes (default 24 = 2 hours, including the 17:00 New York
   close where 5m, 15m, 1H, 4H and 1D all close together) are each timed.

Stores are in memory by default (engine and pipeline CPU). ``--test-db`` runs against a
throwaway PostgreSQL 16 container (same as ``make test-db``; removed afterwards), so database
writes are included. Never point it at a real database.

    .venv/Scripts/python.exe scripts/benchmark.py
    MSYS_NO_PATHCONV=1 .venv/Scripts/python.exe scripts/benchmark.py --test-db

Measured on the development PC; re-run on the client's ARM VM before go-live (AD-03).
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from tradelens.integrations.fakes.synthetic import SyntheticProvider  # noqa: E402
from tradelens.modules.analysis.public import (  # noqa: E402
    CloseBatch,
    CloseProcessor,
    SqlAnalysisStore,
    official_settings,
)
from tradelens.modules.market_data.public import (  # noqa: E402
    IngestService,
    SeriesStatus,
    SqlCandleStore,
    StoredCandle,
    load_instrument_specs,
)
from tradelens.worker.jobs.close import CloseJob  # noqa: E402

# The 24th close lands on Wed 11 Nov 2026 22:00 UTC = 17:00 New York (every timeframe closes).
FIRST = datetime(2026, 11, 11, 20, 5, 2, tzinfo=UTC)
FIVE = timedelta(minutes=5)
AD03_LIMIT_S = 5.0


class MemCandles:
    """In-memory CandleStore (same contract as SqlCandleStore)."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], dict[datetime, StoredCandle]] = {}
        self.status: dict[tuple[str, str], SeriesStatus] = {}
        self.gaps: list[list[Any]] = []

    def last_open_time(self, i: str, tf: str) -> datetime | None:
        """Open time of the newest candle."""
        return max(self.rows.get((i, tf), {}), default=None)

    def open_times(self, i: str, tf: str, since: datetime) -> list[datetime]:
        """Open times from ``since``."""
        return sorted(t for t in self.rows.get((i, tf), {}) if t >= since)

    def load(self, i: str, tf: str, since: datetime | None) -> list[StoredCandle]:
        """Candles from ``since``."""
        rows = self.rows.get((i, tf), {})
        return [rows[t] for t in sorted(rows) if since is None or t >= since]

    def add(self, rows: Sequence[StoredCandle]) -> int:
        """Insert new candles; return how many."""
        n = 0
        for r in rows:
            bucket = self.rows.setdefault((r.instrument, r.timeframe), {})
            if r.open_time not in bucket:
                bucket[r.open_time] = r
                n += 1
        return n

    def get_status(self, i: str, tf: str) -> SeriesStatus | None:
        """The series status."""
        return self.status.get((i, tf))

    def set_status(self, i: str, tf: str, status: SeriesStatus) -> None:
        """Store the series status."""
        self.status[(i, tf)] = status

    def record_gap(self, i: str, tf: str, gf: datetime, gt: datetime, now: datetime) -> None:
        """Record a gap."""
        self.gaps.append([i, tf, gf, gt, now, None])

    def unfilled_gaps(
        self, i: str, tf: str, detected_since: datetime | None = None
    ) -> list[tuple[datetime, datetime]]:
        """Unfilled gaps."""
        return [(g[2], g[3]) for g in self.gaps if g[:2] == [i, tf] and g[5] is None
                and (detected_since is None or g[4] >= detected_since)]  # fmt: skip

    def fill_gap(self, i: str, tf: str, gf: datetime, now: datetime) -> None:
        """Mark a gap filled."""
        for g in self.gaps:
            if g[:3] == [i, tf, gf] and g[5] is None:
                g[5] = now


class MemAnalysis:
    """In-memory AnalysisStore: keeps states and counts output rows."""

    def __init__(self) -> None:
        self.states: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.events: set[str] = set()

    def load_state(self, i: str, tf: str, h: str) -> dict[str, Any] | None:
        """The saved state."""
        return self.states.get((i, tf, h))

    def save_batch(self, batch: CloseBatch) -> None:
        """Keep states and count events."""
        for tf, outs in batch.result.outputs.items():
            self.events.update(e.id for o in outs for e in o.events)
            if outs:
                state = batch.result.states[tf].to_json()
                self.states[(batch.instrument, tf, batch.settings_hash)] = state


class NullRedis:
    """Publisher that drops everything (the benchmark measures the pipeline)."""

    def publish(self, channel: str, message: str) -> int:
        """Drop the message."""
        return 0

    def set(self, name: str, value: str, ex: int | None = None) -> bool:
        """Drop the value."""
        return True


class Clock:
    """A frozen clock moved by the benchmark."""

    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        """The frozen time."""
        return self.now


def processor() -> CloseProcessor:
    """The engine processor for the official r1.0 settings."""
    doc = json.loads((REPO / "config" / "rules" / "r1.0.json").read_text(encoding="utf-8"))
    return CloseProcessor(official_settings(doc), doc["version"])


@contextmanager
def memory_stores() -> Iterator[Any]:
    """Ingest and transaction callables over in-memory stores."""
    candles, analysis = MemCandles(), MemAnalysis()

    @contextmanager
    def transaction() -> Iterator[tuple[MemCandles, MemAnalysis]]:
        yield candles, analysis

    yield (lambda svc, clock: svc.run_once(candles, clock())), transaction


@contextmanager
def test_db_stores() -> Iterator[Any]:
    """Ingest and transaction callables over a throwaway PostgreSQL."""
    import test_db  # the throwaway-container helpers of make test-db
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine

    from tradelens.cli.seed import seed

    test_db.docker("rm", "-f", test_db.NAME, check=False)
    init_dir = (REPO / "deploy" / "postgres-init").as_posix()
    test_db.docker(
        "run", "-d", "--rm", "--name", test_db.NAME, "-p", f"127.0.0.1:{test_db.PORT}:5432",
        "-e", f"POSTGRES_USER={test_db.OWNER}", "-e", f"POSTGRES_PASSWORD={test_db.PASSWORD}",
        "-e", f"POSTGRES_DB={test_db.DB}", "-e", "APP_DB_USER=tradelens_app",
        "-e", f"APP_DB_PASSWORD={test_db.PASSWORD}",
        "-v", f"{init_dir}:/docker-entrypoint-initdb.d:ro", "postgres:16-alpine",
    )  # fmt: skip
    try:
        test_db.wait_ready()
        cfg = Config(str(REPO / "backend" / "alembic.ini"))
        cfg.set_main_option("script_location", str(REPO / "backend" / "migrations"))
        os.environ["DATABASE_MIGRATION_URL"] = test_db.SQLA_URL
        command.upgrade(cfg, "head")
        engine = create_engine(test_db.SQLA_URL)
        with engine.begin() as conn:
            seed(conn, REPO / "config")

        def ingest(svc: IngestService, clock: Clock) -> list[Any]:
            out = []
            for code in svc.instruments:
                with engine.begin() as conn:
                    out.append(svc.ingest_instrument(SqlCandleStore(conn), code, clock()))
            return out

        @contextmanager
        def transaction() -> Iterator[tuple[SqlCandleStore, SqlAnalysisStore]]:
            with engine.begin() as conn:
                yield SqlCandleStore(conn), SqlAnalysisStore(conn)

        yield ingest, transaction
        engine.dispose()
    finally:
        test_db.docker("rm", "-f", test_db.NAME, check=False)


def run(history: int, closes: int, use_db: bool) -> dict[str, Any]:
    """Warm up, then time consecutive close passes."""
    specs = load_instrument_specs(REPO / "config")
    clock = Clock(FIRST - FIVE)
    service = IngestService(SyntheticProvider(specs, clock), specs, history_count=history)
    stores = test_db_stores() if use_db else memory_stores()
    with stores as (ingest, transaction):
        job = CloseJob(ingest=lambda: ingest(service, clock), transaction=transaction,
                       processor=processor(), publisher=NullRedis(), clock=clock)  # fmt: skip
        started = time.perf_counter()
        warm = job.run_once()
        warm_s = time.perf_counter() - started
        series = {(i, tf) for i, b in warm.batches.items() for tf, _ in b.steps}
        per_close = []
        for n in range(closes):
            clock.now = FIRST + n * FIVE
            report = job.run_once()
            steps = sum(len(b.steps) for b in report.batches.values())
            delayed = sum(r.status != "ok" for r in report.reports)
            per_close.append({"close": clock.now.isoformat(), "steps": steps, "delayed": delayed,
                              "seconds": round(report.seconds, 3)})  # fmt: skip
    times = [c["seconds"] for c in per_close]
    return {
        "mode": "test-db (PostgreSQL 16 in Docker)" if use_db else "memory",
        "machine": f"{platform.system()} {platform.release()} {platform.machine()}, "
                   f"Python {platform.python_version()}, {os.cpu_count()} logical CPUs",
        "history_candles": history, "series": len(series),
        "warmup_seconds": round(warm_s, 2),
        "warmup_steps": sum(len(b.steps) for b in warm.batches.values()),
        "closes": closes, "median_s": round(statistics.median(times), 3),
        "max_s": round(max(times), 3), "all_tf_close": per_close[-1],
        "ad03_split_needed": max(times) > AD03_LIMIT_S, "per_close": per_close,
    }  # fmt: skip


def main() -> int:
    """Run the benchmark and print a JSON summary (``--out`` also writes it to a file)."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--history", type=int, default=2500)
    parser.add_argument("--closes", type=int, default=24)
    parser.add_argument("--test-db", action="store_true", help="throwaway PostgreSQL container")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    result = run(args.history, args.closes, args.test_db)
    text = json.dumps({k: v for k, v in result.items() if k != "per_close"}, indent=1)
    sys.stdout.write(text + "\n")
    if args.out:
        args.out.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
