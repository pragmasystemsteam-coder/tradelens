"""Client-side credit budget for the Twelve Data FREE plan (CR-004).

The FREE (Basic) plan allows about 8 API credits a minute and 800 a day (1 credit = 1 symbol
per request). Every call goes through :class:`CreditLimiter`: it waits when the rolling minute
is full and refuses (``BudgetExhaustedError``) once the UTC day is spent, logging each state
change once. The day counter lives in the worker process; a restart starts it again, so the
provider may still answer with its own limit error, which the adapter maps to
``RateLimitedError``.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

from tradelens.modules.market_data.ports import BudgetExhaustedError

FREE_PER_MINUTE = 8
FREE_PER_DAY = 800
WINDOW = timedelta(seconds=60)

log = logging.getLogger("tradelens.market_data.budget")


def _utc_now() -> datetime:
    return datetime.now(UTC)


class CreditLimiter:
    """Rolling 60-second window plus a UTC-day counter of spent credits."""

    def __init__(
        self,
        per_minute: int = FREE_PER_MINUTE,
        per_day: int = FREE_PER_DAY,
        clock: Callable[[], datetime] = _utc_now,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if per_minute < 1 or per_day < 1:
            raise ValueError("credit limits must be positive")
        self._per_minute = per_minute
        self._per_day = per_day
        self._clock = clock
        self._sleep = sleep
        self._window: deque[tuple[datetime, int]] = deque()
        self._day: date | None = None
        self._used_today = 0
        self._exhausted_logged = False
        self._lock = threading.Lock()

    @property
    def remaining_today(self) -> int:
        """Credits left in the current UTC day."""
        with self._lock:
            self._roll_day(self._clock())
            return self._per_day - self._used_today

    def _roll_day(self, now: datetime) -> None:
        today = now.astimezone(UTC).date()
        if today != self._day:
            if self._day is not None and self._exhausted_logged:
                log.info("twelvedata daily credit budget reset", extra={"day": str(today)})
            self._day, self._used_today, self._exhausted_logged = today, 0, False

    def _prune(self, now: datetime) -> int:
        while self._window and now - self._window[0][0] >= WINDOW:
            self._window.popleft()
        return sum(credits for _, credits in self._window)

    def acquire(self, credits: int = 1) -> None:
        """Spend ``credits``, waiting for the minute window when needed.

        Args:
            credits: Credits the next request costs (1 per symbol).

        Raises:
            ValueError: If ``credits`` is not in ``1..per_minute``.
            BudgetExhaustedError: If the UTC day has fewer than ``credits`` left.
        """
        if not 1 <= credits <= self._per_minute:
            raise ValueError(f"credits must be in 1..{self._per_minute}")
        while True:
            with self._lock:
                now = self._clock()
                self._roll_day(now)  # also after a wait that crossed 00:00 UTC
                if self._used_today + credits > self._per_day:
                    if not self._exhausted_logged:
                        log.warning(
                            "twelvedata daily credit budget reached; calls refused until 00:00 UTC",
                            extra={"per_day": self._per_day},
                        )
                        self._exhausted_logged = True
                    raise BudgetExhaustedError(f"daily credit budget of {self._per_day} reached")
                if self._prune(now) + credits <= self._per_minute:
                    self._window.append((now, credits))
                    self._used_today += credits
                    return
                wait = (WINDOW - (now - self._window[0][0])).total_seconds()
            # Sleep outside the lock so status reads (remaining_today) never block.
            log.info(
                "twelvedata minute credit budget full; waiting",
                extra={"wait_seconds": wait, "per_minute": self._per_minute},
            )
            self._sleep(wait)
