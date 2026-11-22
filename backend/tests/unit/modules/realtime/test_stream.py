"""Server-Sent Events: forwarding, throttling, heartbeat and limits (DD 4.4; task 2.8)."""

import asyncio
import contextlib
import json

import pytest
from fake_redis import AsyncFakeRedis, FakeRedis

from tradelens.core.errors import ApiError
from tradelens.core.limits import DEFAULTS, Limits
from tradelens.modules.realtime.service import (
    SLOT_STALE_SECONDS,
    StreamSpec,
    acquire_stream,
    event_stream,
    keep_stream,
    parse_topics,
    release_stream,
)

INSTRUMENTS = {"EUR_USD": "forex", "GBP_USD": "forex", "XAU_USD": "metal", "WTICO_USD": "energy"}
FREE = Limits(dict(DEFAULTS), {**DEFAULTS, "asset_classes": ["forex", "metal", "energy"]})
PRO = Limits({**DEFAULTS, "asset_classes": ["forex", "metal", "energy"]}, FREE.best)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def spec(topics="scanner,chart:EUR_USD,price:EUR_USD", limits=FREE, sid="s1"):
    channels = parse_topics(topics, INSTRUMENTS, limits, user_id="u1")
    allowed = {c for c, a in INSTRUMENTS.items() if limits.allows_asset(a)}
    return StreamSpec(user_id="u1", session_id=sid, channels=channels, instruments=allowed,
                      throttle_s=0.5, ping_s=25.0, poll_s=0.005)  # fmt: skip


async def collect(redis, sp, actions, clock, until=None, rounds=40):
    """Run the stream, applying ``actions`` (callables) between polls; return frames."""
    frames = []
    gen = event_stream(redis.pubsub(), sp, monotonic=clock)
    frames.append(await gen.__anext__())  # retry hint; the subscription is now active
    pending = list(actions)

    async def pump():
        async for f in gen:
            frames.append(f)
            if until and until(frames):
                return

    async def settle():
        # Windows timers are ~15.6 ms coarse: yield a few times, then really wait 20 ms.
        for _ in range(10):
            await asyncio.sleep(0)
        await asyncio.sleep(0.02)

    task = asyncio.ensure_future(pump())
    for _ in range(rounds):
        await settle()
        if pending:
            pending.pop(0)()
        if task.done():
            break
    if not task.done():
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    await gen.aclose()
    return frames


def events(frames, name):
    return [json.loads(f.split("data: ", 1)[1]) for f in frames
            if f.startswith(f"event: {name}\n")]  # fmt: skip


def run(coro):
    return asyncio.run(coro)


def test_scanner_updated_forwarded():
    redis, clock = FakeRedis(), Clock()
    sent = {"timeframe": "1h", "data_as_of": "2026-11-16T12:00:00Z"}
    frames = run(collect(redis, spec(), [lambda: redis.send_event("updates:scanner",
                                                                  "scanner.updated", sent)],
                         clock, until=lambda f: events(f, "scanner.updated")))  # fmt: skip
    assert events(frames, "scanner.updated") == [sent]
    assert frames[0].startswith("retry:")


def test_chart_updated_forwarded():
    redis, clock = FakeRedis(), Clock()
    sent = {"instrument": "EUR_USD", "timeframe": "1h", "last_close": "2026-11-16T12:00:00Z"}
    other = dict(sent, instrument="GBP_USD")
    frames = run(collect(redis, spec(), [
        lambda: redis.send_event("updates:GBP_USD", "chart.updated", other),  # not subscribed
        lambda: redis.send_event("updates:EUR_USD", "chart.updated", sent),
    ], clock, until=lambda f: events(f, "chart.updated")))  # fmt: skip
    assert events(frames, "chart.updated") == [sent]


def test_series_delayed_and_resumed_forwarded():
    redis, clock = FakeRedis(), Clock()
    d = {"instrument": "EUR_USD", "timeframe": "5m", "since": "2026-11-16T12:00:00Z"}
    gold = dict(d, instrument="XAU_USD")
    frames = run(collect(redis, spec(), [
        lambda: redis.send_event("data", "series.delayed", gold),  # not entitled on Free
        lambda: redis.send_event("data", "series.delayed", d),
        lambda: redis.send_event("data", "series.resumed", d),
    ], clock, until=lambda f: events(f, "series.resumed")))  # fmt: skip
    assert events(frames, "series.delayed") == [d]
    assert events(frames, "series.resumed") == [d]


def test_price_throttled_2_per_second():
    redis, clock = FakeRedis(), Clock()

    def tick(mid, advance=0.0):
        def act():
            clock.t += advance
            body = {"instrument": "EUR_USD", "mid": mid, "bid": mid, "ask": mid,
                    "price_scale": 5, "time": "t"}  # fmt: skip
            redis.send_event("prices:EUR_USD", "price", body)

        return act

    def wait(advance):
        def act():
            clock.t += advance

        return act

    # 4 ticks inside 0.3 s: the first goes out, the latest of the rest goes out once 0.5 s
    # has passed; the ones in between are dropped (latest tick wins).
    frames = run(collect(redis, spec(), [tick(1), tick(2, 0.1), tick(3, 0.1), tick(4, 0.1),
                                         wait(0.25), wait(0.0), wait(0.0)],
                         clock, rounds=30))  # fmt: skip
    mids = [p["mid"] for p in events(frames, "price")]
    assert mids == [1, 4]


def test_commodity_topic_refused_free():
    with pytest.raises(ApiError) as err:
        parse_topics("scanner,price:XAU_USD", INSTRUMENTS, FREE, user_id="u1")
    assert err.value.status == 403 and err.value.code == "plan_required"
    assert err.value.details["limit_key"] == "asset_classes"
    channels = parse_topics("chart:XAU_USD,price:WTICO_USD", INSTRUMENTS, PRO, user_id="u1")
    assert {"updates:XAU_USD", "prices:WTICO_USD", "data", "user:u1"} <= set(channels)
    with pytest.raises(ApiError) as err:
        parse_topics("chart:NOPE", INSTRUMENTS, PRO, user_id="u1")
    assert err.value.code == "validation_error"
    with pytest.raises(ApiError):
        parse_topics(",".join(f"chart:EUR_USD{i}" for i in range(21)), INSTRUMENTS, PRO,
                     user_id="u1")  # fmt: skip


def test_session_ended_on_third_login():
    redis, clock = FakeRedis(), Clock()
    frames = run(collect(redis, spec(sid="old"), [
        lambda: redis.send_event("user:u1", "session.ended", {"reason": "signed_in_elsewhere",
                                                               "sessions": ["other"]}),
        lambda: redis.send_event("user:u1", "session.ended", {"reason": "signed_in_elsewhere",
                                                               "sessions": ["old"]}),
    ], clock, rounds=20))  # fmt: skip
    ended = events(frames, "session.ended")
    assert ended == [{"reason": "signed_in_elsewhere"}]  # only this session's, then it closes
    assert frames[-1].startswith("event: session.ended")
    assert redis.subscribers == []  # unsubscribed on close


def test_heartbeat_25s():
    redis, clock = FakeRedis(), Clock()

    def advance(dt):
        def act():
            clock.t += dt

        return act

    frames = run(collect(redis, spec(), [advance(10), advance(10), advance(4.9), advance(0.2),
                                         advance(0.0)], clock, rounds=12))  # fmt: skip
    assert frames.count(": ping\n\n") == 1


def test_max_6_streams():
    async def go():
        aredis = AsyncFakeRedis(FakeRedis())
        slots = [await acquire_stream(aredis, "u1", 6) for _ in range(6)]
        with pytest.raises(ApiError) as err:
            await acquire_stream(aredis, "u1", 6)
        assert err.value.status == 429 and err.value.code == "rate_limited"
        await release_stream(aredis, "u1", slots[0])
        await acquire_stream(aredis, "u1", 6)  # a closed stream frees its slot
        assert await aredis.zcard("sse:slots:u1") == 6

    run(go())


class Tick:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def test_streams_lost_in_a_restart_free_their_slots():
    """A process that dies never releases; its slots lapse after SLOT_STALE_SECONDS."""

    async def go():
        clock = Tick()
        aredis = AsyncFakeRedis(FakeRedis(clock))
        for _ in range(6):
            await acquire_stream(aredis, "u1", 6, now=clock)
        clock.t += SLOT_STALE_SECONDS + 1  # no pings: the API was restarted
        await acquire_stream(aredis, "u1", 6, now=clock)
        assert await aredis.zcard("sse:slots:u1") == 1

    run(go())


def test_open_stream_keeps_its_slot_with_pings():
    async def go():
        clock = Tick()
        aredis = AsyncFakeRedis(FakeRedis(clock))
        slot = await acquire_stream(aredis, "u1", 1, now=clock)
        for _ in range(10):  # 10 pings, far past the stale limit in total
            clock.t += 25
            await keep_stream(aredis, "u1", slot, now=clock)
        with pytest.raises(ApiError):
            await acquire_stream(aredis, "u1", 1, now=clock)

    run(go())


def test_heartbeat_refreshes_the_stream_slot():
    """Review fix: an hour-long stream keeps its slot key alive (calls on_ping each ping)."""
    redis, clock = FakeRedis(), Clock()
    pings = []

    async def go():
        gen = event_stream(redis.pubsub(), spec(), monotonic=clock,
                           on_ping=lambda: pings.append(clock.t))  # fmt: skip
        await gen.__anext__()
        clock.t += 25
        frame_ = await asyncio.wait_for(gen.__anext__(), 1)
        await gen.aclose()
        return frame_

    assert run(go()) == ": ping\n\n"
    assert pings == [1025.0]
