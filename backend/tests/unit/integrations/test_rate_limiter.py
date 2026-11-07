"""Client-side credit budget for the Twelve Data FREE plan: 8 per minute, 800 per day (CR-004)."""

from datetime import UTC, datetime, timedelta

import pytest

from tradelens.integrations.twelvedata.rate_limiter import CreditLimiter
from tradelens.modules.market_data.ports import BudgetExhaustedError


class FakeClock:
    def __init__(self, start):
        self.now = start
        self.slept = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += timedelta(seconds=seconds)


def test_limiter_waits_after_8_credits_in_a_minute():
    clock = FakeClock(datetime(2026, 11, 9, 10, 0, 0, tzinfo=UTC))
    limiter = CreditLimiter(per_minute=8, per_day=800, clock=clock, sleep=clock.sleep)
    for _ in range(8):
        limiter.acquire()
    assert clock.slept == []
    clock.now += timedelta(seconds=20)
    limiter.acquire()  # the 9th credit waits until the first leaves the 60 s window
    assert clock.slept == [40.0]
    assert limiter.remaining_today == 791


def test_limiter_raises_after_800_a_day_and_resets_at_utc_midnight():
    clock = FakeClock(datetime(2026, 11, 9, 23, 0, 0, tzinfo=UTC))
    limiter = CreditLimiter(per_minute=1000, per_day=800, clock=clock, sleep=clock.sleep)
    for _ in range(800):
        limiter.acquire()
    with pytest.raises(BudgetExhaustedError):
        limiter.acquire()
    assert limiter.remaining_today == 0
    clock.now = datetime(2026, 11, 10, 0, 0, 1, tzinfo=UTC)
    limiter.acquire()
    assert limiter.remaining_today == 799


def test_limiter_rejects_impossible_request():
    limiter = CreditLimiter(per_minute=8, per_day=800)
    with pytest.raises(ValueError):
        limiter.acquire(9)
    with pytest.raises(ValueError):
        limiter.acquire(0)


def test_limiter_logs_budget_exhaustion_once(caplog):
    clock = FakeClock(datetime(2026, 11, 9, 10, 0, tzinfo=UTC))
    limiter = CreditLimiter(per_minute=100, per_day=2, clock=clock, sleep=clock.sleep)
    limiter.acquire()
    limiter.acquire()
    for _ in range(3):
        with pytest.raises(BudgetExhaustedError):
            limiter.acquire()
    assert sum("daily credit budget" in r.getMessage() for r in caplog.records) == 1
