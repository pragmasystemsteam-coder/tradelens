"""Worker setups, revisions, scanner cache and live messages (DD 8.2 task 2.3).

Stores are in memory; the SQL store (one transaction, re-processing) is covered by
backend/tests/integration/analysis/test_setup_db.py.
"""

import json
from datetime import timedelta

from setup_batch import FVG, OB, SID, H, T, event, make_batch, scorer, weights

from tradelens.modules.analysis.public import CloseProcessor, official_settings
from tradelens.modules.analysis.setups import setup_from_engine_json
from tradelens.modules.market_data.public import InstrumentReport, SeriesStatus
from tradelens.worker.jobs.close import CloseJob

from .memory_analysis import MemoryAnalysisStore, MemoryStore, MemoryUnitOfWork, RecordingRedis
from .test_close_pipeline import rule_doc

HOUR = timedelta(hours=1)


class BatchProcessor:
    """Stands in for CloseProcessor: each pass saves the next hand-built batch."""

    settings_hash = H

    def __init__(self, *builders):
        self.builders = list(builders)

    def process(self, candles, store, instrument, now):
        if not self.builders:
            return None
        batch = self.builders.pop(0)(store)
        store.save_batch(batch)
        return batch


def open_setups(store):
    return [setup_from_engine_json(d, weights()) for d in store.load_open_setups("EUR_USD", H)]


def job_for(processor, analysis=None, status="ok"):
    analysis = analysis or MemoryAnalysisStore()
    redis = RecordingRedis()
    job = CloseJob(
        ingest=lambda: [InstrumentReport("EUR_USD", status=status, previous_status="ok")],
        transaction=MemoryUnitOfWork(MemoryStore(), analysis),
        processor=processor,
        publisher=redis,
        clock=lambda: T + 3 * HOUR,
        scanner=analysis.scanner_rows,
    )
    return job, analysis, redis


def cached(redis, direction="bull", tf="1h"):
    return json.loads(redis.values[f"scanner:{direction}:{tf}"])


def first(store):
    return make_batch()


def test_scanner_cache_rebuilt_after_close():
    job, analysis, redis = job_for(BatchProcessor(first))
    job.run_once()
    doc = cached(redis)
    assert [r["id"] for r in doc["items"]] == [SID]
    assert doc["data_as_of"] == "2026-11-11T14:00:00Z"
    assert cached(redis, "bear", "1h")["items"] == []
    assert cached(redis, "bull", "15m")["items"] == []
    row = doc["items"][0]
    assert (row["zone"], row["zone_state"], row["status"]) == (
        {"low": 108_000, "high": 108_050},
        "confirmed",
        "confirmed",
    )
    sent = redis.events("scanner.updated")
    assert sorted(d["timeframe"] for _, d in sent) == ["15m", "1h", "4h"]
    assert all(ch == "updates:scanner" for ch, _ in sent)
    assert analysis.setups[SID]["revs"][0].reason == "created"


def test_delayed_series_creates_no_setups():
    proc = CloseProcessor(official_settings(rule_doc()), "r1.0", scorer())
    candles = MemoryStore()
    candles.set_status("EUR_USD", "5m", SeriesStatus("delayed", T, T, T))
    analysis = MemoryAnalysisStore()
    assert proc.process(candles, analysis, "EUR_USD", T + HOUR) is None
    job, analysis, redis = job_for(proc, analysis, status="delayed")
    report = job.run_once()
    assert report.batches == {}
    assert analysis.setups == {}
    assert analysis.saves == 0
    assert redis.events("scanner.updated") == []
    assert not any(k.startswith("scanner:") for k in redis.values)


def test_batch_end_reevaluation_writes_ltf_revision_and_publishes():
    touch = T + HOUR
    confirm = event("c" * 32, "15m", touch + timedelta(minutes=30))

    def second(store):
        return make_batch(first=False, transitions=[(OB, "touched", touch)], events=[confirm],
                          last=T + 2 * HOUR, open_setups=open_setups(store))  # fmt: skip

    job, analysis, redis = job_for(BatchProcessor(first, second))
    job.run_once()
    before = cached(redis)["items"][0]
    job.run_once()
    row = analysis.setups[SID]
    assert [(r.rev, r.reason) for r in row["revs"]] == [(1, "created"), (2, "ltf_confirmation")]
    assert row["setup"].ltf_confirmed_at == confirm.confirm_time
    after = cached(redis)["items"][0]
    assert after["c"] > before["c"]
    assert after["zone_state"] == "touched"
    assert cached(redis)["data_as_of"] == "2026-11-11T16:00:00Z"
    assert len(redis.events("scanner.updated")) == 6  # two passes x three timeframes
    assert [d["timeframe"] for _, d in redis.events("chart.updated")] == ["1h", "1h"]


def test_zone_invalidated_removes_setup_from_scanner_cache():
    def second(store):
        return make_batch(first=False, transitions=[(OB, "invalidated", T + HOUR)],
                          last=T + HOUR, open_setups=open_setups(store))  # fmt: skip

    job, analysis, redis = job_for(BatchProcessor(first, second))
    job.run_once()
    assert [r["id"] for r in cached(redis)["items"]] == [SID]
    job.run_once()
    assert cached(redis)["items"] == []
    row = analysis.setups[SID]
    assert row["setup"].status == "invalidated"
    assert row["revs"][-1].reason == "zone_invalidated"
    assert analysis.load_open_setups("EUR_USD", H) == []
    assert FVG in analysis.zones  # the zones stay (history and charts)
