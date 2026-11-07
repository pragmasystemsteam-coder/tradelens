"""Ingest job: history once, live 5m, gaps/backfill, derived series (FR-DATA-02/03/05/09)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tradelens.integrations.fakes.synthetic import SyntheticProvider
from tradelens.modules.market_data.ingest import IngestService
from tradelens.modules.market_data.ports import BudgetExhaustedError
from tradelens.modules.market_data.public import load_instrument_specs
from tradelens.worker.scheduler import next_run_at

from .memory_store import MemoryStore

REPO = Path(__file__).resolve().parents[5]
T0 = datetime(2026, 11, 10, 15, 2, tzinfo=UTC)  # Tuesday, market open
FIVE = timedelta(minutes=5)


@pytest.fixture(scope="module")
def specs():
    return [s for s in load_instrument_specs(REPO / "config") if s.code in ("EUR_USD", "XAU_USD")]


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


class Spy:
    """Wraps a provider: records calls, can hide bars from live (non-range) fetches or fail."""

    def __init__(self, inner):
        self.inner, self.calls, self.hidden = inner, [], set()
        self.hide_in_backfill, self.error = False, None
        self.name = inner.name

    def source_for(self, instrument):
        return self.inner.source_for(instrument)

    def fetch(self, instrument, timeframe, *, count, start=None, end=None):
        self.calls.append((instrument, timeframe, count, start, end))
        if self.error:
            raise self.error
        bars = self.inner.fetch(instrument, timeframe, count=count, start=start, end=end)
        if end is None or self.hide_in_backfill:
            bars = [b for b in bars if b.open_time not in self.hidden]
        return bars


def make(specs, now=T0, history=50):
    clock = Clock(now)
    spy = Spy(SyntheticProvider(specs, clock))
    return clock, spy, IngestService(spy, specs, history_count=history), MemoryStore()


def test_history_fetched_once_then_incremental(specs):
    clock, spy, svc, store = make(specs)
    svc.ingest_instrument(store, "EUR_USD", clock.now)
    assert [(c[1], c[2]) for c in spy.calls] == [("5m", 50), ("15m", 50), ("1h", 50)]
    before = len(store.candles[("EUR_USD", "5m")])
    spy.calls.clear()
    clock.now += FIVE
    svc.ingest_instrument(store, "EUR_USD", clock.now)
    assert len(spy.calls) == 1
    instrument, tf, _, start, _ = spy.calls[0]
    assert (instrument, tf, start) == ("EUR_USD", "5m", datetime(2026, 11, 10, 15, 0, tzinfo=UTC))
    assert len(store.candles[("EUR_USD", "5m")]) == before + 1


def test_forming_bar_never_stored(specs):
    clock, _, svc, store = make(specs)
    svc.ingest_instrument(store, "EUR_USD", clock.now)
    assert store.last_open_time("EUR_USD", "5m") == datetime(2026, 11, 10, 14, 55, tzinfo=UTC)
    assert store.last_open_time("EUR_USD", "1h") == datetime(2026, 11, 10, 14, 0, tzinfo=UTC)
    for (_, tf), rows in store.candles.items():
        assert all(c.close_time <= clock.now for c in rows.values()), tf


def test_all_timeframes_ok_after_first_run(specs):
    clock, _, svc, store = make(specs, history=300)
    report = svc.ingest_instrument(store, "XAU_USD", clock.now)
    assert report.errors == []
    for tf in ("5m", "15m", "1h", "4h", "1d"):
        st = store.get_status("XAU_USD", tf)
        assert st.status == "ok", tf
        assert st.last_candle_time == store.last_open_time("XAU_USD", tf)
    assert store.last_open_time("XAU_USD", "4h") is not None
    assert store.last_open_time("XAU_USD", "1d") is not None


def test_derived_series_built_after_source(specs):
    clock, _, svc, store = make(specs)
    svc.ingest_instrument(store, "EUR_USD", clock.now)
    clock.now = datetime(2026, 11, 10, 16, 2, tzinfo=UTC)
    svc.ingest_instrument(store, "EUR_USD", clock.now)
    h = store.candles[("EUR_USD", "1h")][datetime(2026, 11, 10, 15, 0, tzinfo=UTC)]
    raw = SyntheticProvider(specs, clock).fetch("EUR_USD", "1h", count=2)[0]
    assert raw.open_time == h.open_time
    assert (h.o, h.h, h.l, h.c) == (raw.o, raw.h, raw.l, raw.c)
    assert datetime(2026, 11, 10, 15, 45, tzinfo=UTC) in store.candles[("EUR_USD", "15m")]


def test_gap_delays_backfills_resumes(specs):
    clock, spy, svc, store = make(specs)
    svc.ingest_instrument(store, "EUR_USD", clock.now)
    missing = datetime(2026, 11, 10, 15, 5, tzinfo=UTC)
    spy.hidden = {missing}
    spy.hide_in_backfill = True
    clock.now = datetime(2026, 11, 10, 15, 17, tzinfo=UTC)
    svc.ingest_instrument(store, "EUR_USD", clock.now)
    st = store.get_status("EUR_USD", "5m")
    assert st.status == "delayed"
    assert st.delayed_since == clock.now
    assert store.unfilled_gaps("EUR_USD", "5m") == [(missing, missing + FIVE)]
    assert store.get_status("EUR_USD", "15m").status == "delayed"
    # The provider has the bar now: the next run backfills it and the series resumes.
    spy.hide_in_backfill = False
    clock.now += FIVE
    svc.ingest_instrument(store, "EUR_USD", clock.now)
    assert missing in store.candles[("EUR_USD", "5m")]
    assert store.unfilled_gaps("EUR_USD", "5m") == []
    assert store.gaps[0]["filled_at"] == clock.now
    st = store.get_status("EUR_USD", "5m")
    assert (st.status, st.delayed_since) == ("ok", None)
    assert datetime(2026, 11, 10, 15, 0, tzinfo=UTC) in store.candles[("EUR_USD", "15m")]


def test_late_bar_within_grace_is_not_delayed(specs):
    clock, spy, svc, store = make(specs)
    svc.ingest_instrument(store, "EUR_USD", clock.now)
    spy.hidden = {datetime(2026, 11, 10, 15, 0, tzinfo=UTC)}
    clock.now = datetime(2026, 11, 10, 15, 5, 30, tzinfo=UTC)  # the bar closed 30 s ago
    svc.ingest_instrument(store, "EUR_USD", clock.now)
    assert store.get_status("EUR_USD", "5m").status == "ok"
    clock.now = datetime(2026, 11, 10, 15, 6, 30, tzinfo=UTC)  # 90 s late: delayed
    svc.ingest_instrument(store, "EUR_USD", clock.now)
    assert store.get_status("EUR_USD", "5m").status == "delayed"


def test_budget_exhausted_marks_delayed_not_crash(specs):
    clock, spy, svc, store = make(specs)
    svc.ingest_instrument(store, "EUR_USD", clock.now)
    spy.error = BudgetExhaustedError("daily credit budget of 800 reached")
    clock.now = datetime(2026, 11, 10, 15, 12, tzinfo=UTC)
    report = svc.ingest_instrument(store, "EUR_USD", clock.now)
    assert report.errors
    assert "budget" in report.errors[0]
    statuses = {store.get_status("EUR_USD", tf).status for tf in ("5m", "15m", "1h", "4h", "1d")}
    assert statuses == {"delayed"}


def test_weekend_run_fetches_nothing_new_and_stays_ok(specs):
    sat = datetime(2026, 11, 7, 12, 2, tzinfo=UTC)
    clock, spy, svc, store = make(specs, now=sat)
    svc.ingest_instrument(store, "EUR_USD", clock.now)
    spy.calls.clear()
    clock.now += timedelta(hours=1)
    svc.ingest_instrument(store, "EUR_USD", clock.now)
    assert spy.calls == []  # nothing can be due while the market is closed
    assert store.get_status("EUR_USD", "5m").status == "ok"


def test_run_once_covers_every_instrument(specs):
    clock, _, svc, store = make(specs)
    reports = svc.run_once(store, clock.now)
    assert [r.instrument for r in reports] == ["EUR_USD", "XAU_USD"]
    assert len(store.status) == 10


def test_next_run_on_5_minute_boundary_plus_offset():
    def utc(*a):
        return datetime(*a, tzinfo=UTC)

    assert next_run_at(utc(2026, 11, 10, 15, 2, 10), 300, 2) == utc(2026, 11, 10, 15, 5, 2)
    assert next_run_at(utc(2026, 11, 10, 15, 5, 2), 300, 2) == utc(2026, 11, 10, 15, 10, 2)
    assert next_run_at(utc(2026, 11, 10, 15, 5, 1), 300, 2) == utc(2026, 11, 10, 15, 5, 2)


def test_bars_outside_trading_hours_dropped(specs):
    """Live check 7 Nov 2026: Twelve Data sent EUR/USD 5m bars on a Saturday; never store them."""
    from tradelens.modules.market_data.ports import RawBar

    sat = datetime(2026, 11, 7, 6, 57, tzinfo=UTC)
    store = MemoryStore()
    weekend = [RawBar(datetime(2026, 11, 7, 6, 40, tzinfo=UTC), 111403, 111403, 111403, 111403)]

    class Weekend:
        name = "twelvedata"

        def source_for(self, instrument):
            return "twelvedata"

        def fetch(self, instrument, timeframe, *, count, start=None, end=None):
            return weekend

    svc2 = IngestService(Weekend(), specs, history_count=50)
    svc2.ingest_instrument(store, "EUR_USD", sat)
    assert store.last_open_time("EUR_USD", "5m") is None


def test_late_source_candle_still_builds_derived_buckets(specs):
    """Review H2: a 1h bucket that waited for a late 5m candle is built once it is complete."""
    clock, spy, svc, store = make(specs)
    svc.ingest_instrument(store, "EUR_USD", clock.now)
    missing = datetime(2026, 11, 10, 15, 5, tzinfo=UTC)
    spy.hidden, spy.hide_in_backfill = {missing}, True
    for minutes in range(17, 125, 5):  # until 17:02, long after the gap stopped being retried
        clock.now = datetime(2026, 11, 10, 15, 0, tzinfo=UTC) + timedelta(minutes=minutes)
        svc.ingest_instrument(store, "EUR_USD", clock.now)
    hour = datetime(2026, 11, 10, 15, 0, tzinfo=UTC)
    assert datetime(2026, 11, 10, 16, 0, tzinfo=UTC) in store.candles[("EUR_USD", "1h")]
    assert hour not in store.candles[("EUR_USD", "1h")]
    late = SyntheticProvider(specs, clock).fetch(
        "EUR_USD", "5m", count=1, start=missing, end=missing
    )
    from tradelens.modules.market_data.candles import to_stored

    store.add([to_stored(late[0], "EUR_USD", "5m", "fake")])  # e.g. a manual backfill
    clock.now += FIVE
    svc.ingest_instrument(store, "EUR_USD", clock.now)
    assert hour in store.candles[("EUR_USD", "1h")]
    assert hour in store.candles[("EUR_USD", "15m")]


def test_rate_limit_stops_remaining_calls_of_the_pass(specs):
    from tradelens.modules.market_data.ports import RateLimitedError

    clock, spy, svc, store = make(specs)
    spy.error = RateLimitedError("twelvedata: credit limit reached")
    report = svc.ingest_instrument(store, "EUR_USD", clock.now)
    assert len(spy.calls) == 1  # history for 15m and 1h is not attempted in this pass
    assert report.status == "delayed"
