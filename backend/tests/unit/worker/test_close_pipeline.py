"""Candle-close pipeline with the fake provider and a frozen clock (DD 8.1 task 1.9).

Ingest -> status -> engine step (highest timeframe first) -> one save per instrument ->
Redis messages. Stores are in memory; the SQL store and its single transaction are covered
by backend/tests/integration/analysis/test_close_db.py.
"""

import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tradelens.integrations.fakes.synthetic import SyntheticProvider
from tradelens.modules.analysis.public import CloseProcessor, official_settings
from tradelens.modules.market_data.public import IngestService, load_instrument_specs
from tradelens.worker.jobs.close import CloseJob
from tradelens_engine.multi import run_multi
from tradelens_engine.types import Candle

from .memory_analysis import MemoryAnalysisStore, MemoryStore, MemoryUnitOfWork, RecordingRedis

REPO = Path(__file__).resolve().parents[4]
TFS = ("5m", "15m", "1h", "4h", "1d")
# Wednesday 11 Nov 2026, 21:55:02 UTC; the next pass at 22:00:02 closes all five timeframes
# (17:00 New York is the daily close in winter).
T0 = datetime(2026, 11, 11, 21, 55, 2, tzinfo=UTC)
FIVE = timedelta(minutes=5)


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


class HoleProvider:
    """Synthetic bars, but bars at ``holes`` are missing for the first ``misses`` calls."""

    def __init__(self, inner, holes, misses):
        self.inner, self.holes, self.misses = inner, set(holes), misses
        self.name = inner.name

    def source_for(self, instrument):
        return self.inner.source_for(instrument)

    def fetch(self, instrument, timeframe, **kw):
        bars = self.inner.fetch(instrument, timeframe, **kw)
        hit = timeframe == "5m" and any(b.open_time in self.holes for b in bars)
        if hit and self.misses > 0:
            self.misses -= 1
            return [b for b in bars if b.open_time not in self.holes]
        return bars


class WithholdProvider:
    """Synthetic bars, but nothing that opens at or after ``since`` (no complete candle yet)."""

    def __init__(self, inner, since):
        self.inner, self.since = inner, since
        self.name = inner.name

    def source_for(self, instrument):
        return self.inner.source_for(instrument)

    def fetch(self, instrument, timeframe, **kw):
        bars = self.inner.fetch(instrument, timeframe, **kw)
        return [b for b in bars if b.open_time < self.since]


def specs(codes=None):
    all_specs = load_instrument_specs(REPO / "config")
    return [s for s in all_specs if codes is None or s.code in codes]


def rule_doc():
    return json.loads((REPO / "config" / "rules" / "r1.0.json").read_text(encoding="utf-8"))


def pipeline(clock, provider, instruments, history=300, candles=None, analysis=None):
    sp = specs(instruments)
    candles = candles or MemoryStore()
    analysis = analysis or MemoryAnalysisStore()
    ingest = IngestService(provider, sp, history_count=history)
    redis = RecordingRedis()
    job = CloseJob(
        ingest=lambda: ingest.run_once(candles, clock()),
        transaction=MemoryUnitOfWork(candles, analysis),
        processor=CloseProcessor(official_settings(rule_doc()), "r1.0"),
        publisher=redis,
        clock=clock,
    )
    return job, candles, analysis, redis


def engine_candles(store, instrument, tf):
    return [
        Candle(c.open_time, c.close_time, c.o, c.h, c.l, c.c, c.bid_c, c.ask_c)
        for c in store.load(instrument, tf, None)
    ]


def batch_run_ids(store, instrument):
    """Event IDs of one uninterrupted engine run over everything stored."""
    series = {tf: engine_candles(store, instrument, tf) for tf in TFS}
    series = {tf: cs for tf, cs in series.items() if cs}
    cfg = official_settings(rule_doc())
    result = run_multi(series, cfg, instrument=instrument, rule_version="r1.0")
    return sorted(e.id for r in result.values() for e in r.events)


def test_close_batch_highest_tf_first():
    clock = Clock(T0)
    job, *_ = pipeline(clock, SyntheticProvider(specs(), clock), {"EUR_USD"})
    job.run_once()
    clock.now = T0 + FIVE
    report = job.run_once()
    steps = report.batches["EUR_USD"].steps
    close = datetime(2026, 11, 11, 22, 0, tzinfo=UTC)
    assert [tf for tf, t in steps if t == close] == ["1d", "4h", "1h", "15m", "5m"]


def test_one_save_per_instrument_with_events_and_state():
    clock = Clock(T0)
    job, _, analysis, _ = pipeline(clock, SyntheticProvider(specs(), clock), {"EUR_USD"})
    job.run_once()
    assert analysis.saves == 1  # events, zones, transitions and states: one transaction
    assert {k[1] for k in analysis.states} == set(TFS)
    assert analysis.events


def test_gap_delays_backfills_resumes():
    clock = Clock(datetime(2026, 11, 11, 12, 0, 2, tzinfo=UTC))
    hole = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
    # History (forming bar), live, live + backfill: four fetches miss the bar.
    provider = HoleProvider(SyntheticProvider(specs(), clock), [hole], misses=4)
    job, candles, analysis, redis = pipeline(clock, provider, {"EUR_USD"})
    statuses = []
    for _ in range(4):  # 12:00:02 history, 12:05:02 bar missing, 12:10:02 gap, 12:15:02 filled
        statuses.append(job.run_once().reports[0].status)
        clock.now += FIVE
    assert statuses == ["ok", "ok", "delayed", "ok"]
    assert [d["timeframe"] for _, d in redis.events("series.delayed")] == list(TFS)
    assert [d["timeframe"] for _, d in redis.events("series.resumed")] == list(TFS)
    assert all(ch == "data" for ch, _ in redis.events("series.delayed"))
    gap = candles.gaps[0]
    assert (gap["gap_from"], gap["filled_at"] is not None) == (hole, True)
    state = analysis.states[("EUR_USD", "5m", official_settings(rule_doc()).hash("r1.0"))]
    assert state["last_open_time"] == "2026-11-11T12:10:00Z"
    assert analysis.event_ids() == batch_run_ids(candles, "EUR_USD")


def test_restart_continues_same_events():
    clock = Clock(T0)
    job, candles, analysis, _ = pipeline(clock, SyntheticProvider(specs(), clock), {"EUR_USD"})
    for _ in range(3):
        job.run_once()
        clock.now += FIVE
    # Restart: a new job and processor; only the stores survive (database).
    job2, *_ = pipeline(clock, SyntheticProvider(specs(), clock), {"EUR_USD"},
                        candles=candles, analysis=analysis)  # fmt: skip
    for _ in range(3):
        job2.run_once()
        clock.now += FIVE
    assert analysis.event_ids() == batch_run_ids(candles, "EUR_USD")


def test_corrupt_state_rebuilds_from_candles():
    clock = Clock(T0)
    job, candles, analysis, _ = pipeline(clock, SyntheticProvider(specs(), clock), {"EUR_USD"})
    job.run_once()
    for key in analysis.states:
        analysis.states[key] = {"v": 1}  # an old state layout
    clock.now += FIVE
    job.run_once()
    assert analysis.event_ids() == batch_run_ids(candles, "EUR_USD")


def test_close_processed_under_10s():
    clock = Clock(T0)
    job, *_ = pipeline(clock, SyntheticProvider(specs(), clock), None)
    job.run_once()  # history and warm-up, not timed
    clock.now = T0 + FIVE
    started = time.perf_counter()
    report = job.run_once()
    elapsed = time.perf_counter() - started
    stepped = {(i, tf) for i, b in report.batches.items() for tf, _ in b.steps}
    assert len(report.batches) == 11
    assert {tf for i, tf in stepped if i == "EUR_USD"} == set(TFS)
    assert len({i for i, _ in stepped}) * len(TFS) == 55
    assert elapsed < 10, f"close batch for 55 series took {elapsed:.2f} s"
    assert report.seconds == pytest.approx(elapsed, abs=0.5)


@pytest.mark.parametrize(
    ("friday_close", "sunday_open"),
    [
        # Normal week: Sunday 8 Nov 2026 17:00 New York = 22:00 UTC.
        (datetime(2026, 11, 6, 22, 0, tzinfo=UTC), datetime(2026, 11, 8, 22, 0, tzinfo=UTC)),
        # DST week: clocks went forward that Sunday; 17:00 New York = 21:00 UTC.
        (datetime(2026, 3, 6, 22, 0, tzinfo=UTC), datetime(2026, 3, 8, 21, 0, tzinfo=UTC)),
    ],
)
def test_incomplete_candle_at_sunday_open_and_dst_week_marks_delayed_never_stepped(
    friday_close, sunday_open
):
    clock = Clock(friday_close + timedelta(seconds=2))
    provider = SyntheticProvider(specs(), clock)
    job, candles, analysis, redis = pipeline(clock, provider, {"EUR_USD"})
    assert job.run_once().reports[0].status == "ok"
    before = dict(analysis.states)
    events_before = set(analysis.events)
    # Sunday open: the provider has no complete first candle 65 s after it should have closed.
    job2, _, _, redis2 = pipeline(clock, WithholdProvider(provider, sunday_open), {"EUR_USD"},
                                  candles=candles, analysis=analysis)  # fmt: skip
    clock.now = sunday_open + FIVE + timedelta(seconds=65)
    report = job2.run_once()
    assert report.reports[0].status == "delayed"
    assert "EUR_USD" not in report.batches  # never stepped
    assert analysis.states == before and set(analysis.events) == events_before
    assert all(s.status == "delayed" for s in candles.status.values())
    assert [d["timeframe"] for _, d in redis2.events("series.delayed")] == list(TFS)
    # Once the candle arrives the series resumes and that candle is stepped.
    report = job.run_once()
    assert report.reports[0].status == "ok"
    assert ("5m", sunday_open + FIVE) in report.batches["EUR_USD"].steps
    assert [d["timeframe"] for _, d in redis.events("series.resumed")] == list(TFS)


def test_chart_updated_published_per_stepped_timeframe():
    clock = Clock(T0)
    job, _, _, redis = pipeline(clock, SyntheticProvider(specs(), clock), {"EUR_USD"})
    job.run_once()
    redis.published.clear()
    clock.now = T0 + FIVE
    job.run_once()
    updated = redis.events("chart.updated")
    assert {ch for ch, _ in updated} == {"updates:EUR_USD"}
    assert sorted(d["timeframe"] for _, d in updated) == sorted(TFS)
    assert all(d["last_close"] == "2026-11-11T22:00:00Z" for _, d in updated)
