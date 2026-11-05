from tradelens.worker.healthcheck import check
from tradelens.worker.heartbeat import HEARTBEAT_KEY, beat


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.expiry: dict[str, int | None] = {}

    def get(self, key: str):
        return self.store.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.store[key] = value
        self.expiry[key] = ex
        return True


class BrokenRedis:
    def get(self, key: str):
        raise ConnectionError("redis down")


def test_worker_healthcheck_exit_0_with_heartbeat():
    redis = FakeRedis()
    beat(redis, now=1000.0, ttl=15)
    assert check(redis, now=1003.0, ttl=15) == 0


def test_worker_healthcheck_exit_1_without_heartbeat():
    assert check(FakeRedis(), now=1000.0, ttl=15) == 1


def test_worker_healthcheck_exit_1_when_stale():
    redis = FakeRedis()
    beat(redis, now=1000.0, ttl=15)
    assert check(redis, now=1020.0, ttl=15) == 1


def test_worker_healthcheck_exit_1_when_redis_unreachable():
    assert check(BrokenRedis(), now=1000.0, ttl=15) == 1


def test_worker_healthcheck_exit_1_on_garbage_value():
    redis = FakeRedis()
    redis.set(HEARTBEAT_KEY, "not-a-number")
    assert check(redis, now=1000.0, ttl=15) == 1


def test_beat_sets_key_with_ttl():
    redis = FakeRedis()
    beat(redis, now=1234.5, ttl=15)
    assert redis.store[HEARTBEAT_KEY] == "1234.5"
    assert redis.expiry[HEARTBEAT_KEY] == 15
