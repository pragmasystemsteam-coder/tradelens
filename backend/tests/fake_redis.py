"""In-memory Redis for API tests: strings with TTL, counters and pub/sub (sync and asyncio).

Only the commands the API uses. Time comes from ``clock`` so TTLs follow a frozen test clock.
"""

import asyncio
import json
import time


class FakeRedis:
    def __init__(self, clock=None):
        self.clock = clock or time.time
        self.data = {}  # name -> (value, expires_at | None)
        self.published = []  # (channel, message)
        self.subscribers = []  # FakePubSub

    # ------------------------------------------------------------------ strings
    def _now(self):
        now = self.clock()
        return now.timestamp() if hasattr(now, "timestamp") else now

    def _live(self, name):
        item = self.data.get(name)
        if item is None:
            return None
        _, exp = item
        if exp is not None and exp <= self._now():
            del self.data[name]
            return None
        return item

    def get(self, name):
        item = self._live(name)
        return None if item is None else item[0]

    def set(self, name, value, ex=None, nx=False):
        if nx and self._live(name) is not None:
            return None
        self.data[name] = (str(value), None if ex is None else self._now() + ex)
        return True

    def delete(self, *names):
        n = 0
        for name in names:
            n += self.data.pop(name, None) is not None
        return n

    def incr(self, name):
        item = self._live(name)
        value = 1 if item is None else int(item[0]) + 1
        self.data[name] = (str(value), None if item is None else item[1])
        return value

    def decr(self, name):
        item = self._live(name)
        value = -1 if item is None else int(item[0]) - 1
        self.data[name] = (str(value), None if item is None else item[1])
        return value

    def expire(self, name, time):
        item = self._live(name)
        if item is None:
            return False
        self.data[name] = (item[0], self._now() + time)
        return True

    def ttl(self, name):
        item = self._live(name)
        if item is None:
            return -2
        return -1 if item[1] is None else max(int(item[1] - self._now()), 0)

    def mget(self, names):
        return [self.get(n) for n in names]

    def ping(self):
        return True

    # ------------------------------------------------------------------ pub/sub
    def publish(self, channel, message):
        self.published.append((channel, message))
        for sub in list(self.subscribers):
            sub.deliver(channel, message)
        return len(self.subscribers)

    def send_event(self, channel, event, data):
        """What the worker's ``publish.send`` puts on a channel."""
        return self.publish(channel, json.dumps({"event": event, "data": data}))

    def pubsub(self, **kwargs):
        sub = FakePubSub(self)
        self.subscribers.append(sub)
        return sub


class FakePubSub:
    """asyncio pub/sub: ``subscribe``, ``get_message(timeout=)``, ``aclose``."""

    def __init__(self, redis):
        self.redis = redis
        self.channels = set()
        self.queue = asyncio.Queue()
        self.closed = False

    def deliver(self, channel, message):
        if channel in self.channels and not self.closed:
            self.queue.put_nowait({"type": "message", "channel": channel, "data": message})

    async def subscribe(self, *channels):
        self.channels.update(channels)

    async def unsubscribe(self, *channels):
        self.channels.difference_update(channels)

    async def get_message(self, ignore_subscribe_messages=True, timeout=None):
        try:
            return await asyncio.wait_for(self.queue.get(), timeout)
        except TimeoutError:
            return None

    async def aclose(self):
        self.closed = True
        if self in self.redis.subscribers:
            self.redis.subscribers.remove(self)


class AsyncFakeRedis:
    """The asyncio face of a FakeRedis (same data)."""

    def __init__(self, sync):
        self.sync = sync

    def pubsub(self, **kwargs):
        return self.sync.pubsub(**kwargs)

    async def incr(self, name):
        return self.sync.incr(name)

    async def decr(self, name):
        return self.sync.decr(name)

    async def expire(self, name, time):
        return self.sync.expire(name, time)

    async def get(self, name):
        return self.sync.get(name)

    async def set(self, name, value, ex=None):
        return self.sync.set(name, value, ex=ex)
