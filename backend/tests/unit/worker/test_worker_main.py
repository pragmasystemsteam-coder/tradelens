"""Worker heartbeat loop (Detailed Design 4.8: heartbeat every 5 s, TTL 15 s)."""

import threading

from tradelens.worker.heartbeat import HEARTBEAT_KEY
from tradelens.worker.main import run_heartbeat


class StoppingRedis:
    """Records beats and stops the loop after the given number of writes."""

    def __init__(self, stop: threading.Event, beats_before_stop: int) -> None:
        self.stop, self.left = stop, beats_before_stop
        self.writes: list[tuple[str, str, int | None]] = []

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.writes.append((key, value, ex))
        self.left -= 1
        if self.left == 0:
            self.stop.set()
        return True


class FailingRedis:
    def __init__(self, stop: threading.Event) -> None:
        self.stop, self.calls = stop, 0

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.calls += 1
        if self.calls == 2:
            self.stop.set()
        raise ConnectionError("redis down")


def test_run_heartbeat_writes_until_stopped():
    stop = threading.Event()
    redis = StoppingRedis(stop, beats_before_stop=3)
    ticks = iter([100.0, 105.0, 110.0])
    run_heartbeat(redis, interval=0, ttl=15, stop=stop, clock=lambda: next(ticks))
    assert redis.writes == [
        (HEARTBEAT_KEY, "100.0", 15),
        (HEARTBEAT_KEY, "105.0", 15),
        (HEARTBEAT_KEY, "110.0", 15),
    ]


def test_run_heartbeat_survives_redis_errors():
    stop = threading.Event()
    redis = FailingRedis(stop)
    run_heartbeat(redis, interval=0, ttl=15, stop=stop, clock=lambda: 1.0)
    assert redis.calls == 2
