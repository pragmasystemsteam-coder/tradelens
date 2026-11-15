"""Load check: 100 concurrent scanner loads and 100 SSE streams, p95 under 2 s (task 2.10).

NFR-01 and NFR-04. Signs in the given users (the API allows 6 streams per user, so 100
streams need at least 17 users), then at the same moment fires ``LOADS`` ``GET /setups``
requests and opens ``STREAMS`` ``GET /stream`` connections, timing each request until its
full response and each stream until its first frame. Exits 1 when a p95 is 2 s or more or a
request fails.

Usage (normally through ``python scripts/e2e.py --load``, which starts a throwaway stack and
creates the users)::

    python scripts/loadcheck.py --base http://127.0.0.1:8100 --origin http://localhost:3100 \
        --users users.json   # [{"email": ..., "password": ...}, ...]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

import httpx

LOADS = 100
STREAMS = 100
TARGET_P95_S = 2.0
STREAMS_PER_USER = 6


def p95(values: list[float]) -> float:
    """95th percentile (inclusive method); 0 for no values."""
    if len(values) < 2:  # noqa: PLR2004
        return values[0] if values else 0.0
    return statistics.quantiles(values, n=20, method="inclusive")[18]


async def sign_in(base: str, origin: str, user: dict[str, str]) -> httpx.AsyncClient:
    """A client holding the user's session cookie."""
    client = httpx.AsyncClient(base_url=base, timeout=30, headers={"Origin": origin})
    r = await client.post("/api/v1/auth/login", json=user)
    r.raise_for_status()
    # httpx never sends a Secure cookie over plain http (the local stack): send it by hand.
    token = r.cookies.get("__Host-tl_session")
    if not token:
        raise SystemExit("login returned no session cookie")
    client.cookies.clear()
    client.headers["Cookie"] = f"__Host-tl_session={token}"
    return client


async def timed_get(client: httpx.AsyncClient, path: str) -> float:
    """Seconds until the whole response arrived."""
    started = time.perf_counter()
    r = await client.get(path)
    r.raise_for_status()
    return time.perf_counter() - started


async def timed_stream(client: httpx.AsyncClient, hold: asyncio.Event) -> float:
    """Seconds until the first SSE frame; keeps the stream open until ``hold`` is set."""
    started = time.perf_counter()
    async with client.stream("GET", "/api/v1/stream", params={"topics": "scanner"}) as r:
        r.raise_for_status()
        async for _ in r.aiter_text():
            first = time.perf_counter() - started
            break
        else:
            raise RuntimeError("stream closed before its first frame")
        await hold.wait()
    return first


async def run(base: str, origin: str, users: list[dict[str, str]]) -> dict[str, float]:
    """Sign in, fire the load, return the timings."""
    need = -(-STREAMS // STREAMS_PER_USER)
    if len(users) < need:
        raise SystemExit(f"{STREAMS} streams need at least {need} users")
    clients = [await sign_in(base, origin, u) for u in users]
    hold = asyncio.Event()
    try:
        streams = [asyncio.create_task(timed_stream(clients[i // STREAMS_PER_USER], hold))
                   for i in range(STREAMS)]  # fmt: skip
        # Rate limit is 120 a minute per user: spread the loads over the users too.
        loads = [timed_get(clients[i % len(clients)], "/api/v1/setups") for i in range(LOADS)]
        load_times = await asyncio.gather(*loads)
        await asyncio.sleep(0.5)
        hold.set()
        stream_times = await asyncio.gather(*streams)
    finally:
        hold.set()
        for c in clients:
            await c.aclose()
    return {
        "loads": LOADS, "streams": STREAMS,
        "setups_p95_s": round(p95(list(load_times)), 3),
        "setups_max_s": round(max(load_times), 3),
        "stream_first_frame_p95_s": round(p95(list(stream_times)), 3),
        "stream_first_frame_max_s": round(max(stream_times), 3),
    }  # fmt: skip


def main() -> int:
    """Parse arguments, run the check, print the result as JSON."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", required=True, help="API base URL")
    parser.add_argument("--origin", required=True, help="APP_URL of the API (Origin header)")
    parser.add_argument("--users", required=True, type=Path, help="JSON list of email/password")
    args = parser.parse_args()
    users = json.loads(args.users.read_text(encoding="utf-8"))
    result = asyncio.run(run(args.base, args.origin, users))
    ok = result["setups_p95_s"] < TARGET_P95_S and result["stream_first_frame_p95_s"] < TARGET_P95_S
    sys.stdout.write(json.dumps({**result, "target_p95_s": TARGET_P95_S, "pass": ok}) + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
