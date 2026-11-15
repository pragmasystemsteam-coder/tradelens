"""Review fixes (Day 5): CSRF compare, secret checks and SSE slot release."""

import asyncio

import pytest
from api_support import make_config
from fake_redis import AsyncFakeRedis, FakeRedis

from tradelens.app.main import create_app
from tradelens.core.security import csrf_ok, csrf_token
from tradelens.modules.realtime.service import release_stream


def test_csrf_non_ascii_header_is_refused_not_an_error():
    sid = "a" * 64
    assert csrf_ok("c" * 32, sid, csrf_token("c" * 32, sid))
    assert not csrf_ok("c" * 32, sid, "é" * 64)  # latin-1 header: False, never TypeError
    assert not csrf_ok("c" * 32, sid, None)


@pytest.mark.parametrize("env", ["production", "staging", "qa", ""])
def test_weak_or_shared_secrets_refused_outside_development(env):
    for secrets in ({"session_secret": "", "csrf_secret": ""},
                    {"session_secret": "short", "csrf_secret": "x" * 32},
                    {"session_secret": "s" * 32, "csrf_secret": "s" * 32}):  # fmt: skip
        with pytest.raises(RuntimeError):
            create_app(make_config(app_env=env, **secrets))


def test_development_and_test_may_run_without_secrets():
    create_app(make_config(app_env="development", session_secret="", csrf_secret=""))
    create_app(make_config(app_env="test", session_secret="", csrf_secret=""))


def test_stream_slot_never_goes_negative():
    async def go():
        aredis = AsyncFakeRedis(FakeRedis())
        await release_stream(aredis, "u1")  # key expired while streams were open
        assert int(await aredis.get("sse:u1") or 0) == 0

    asyncio.run(go())
