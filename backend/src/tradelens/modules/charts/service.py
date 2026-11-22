"""Chart payloads and candle pages (DD 4.2 charts and candles, 4.3; task 2.6; FR-CHART-01..05).

History: the user may scroll back at most ``chart_history_candles`` candles from the newest
one (500 Free, 2,000 Pro); a page holds ``limit`` of them (``before`` pages back). Official
settings read stored rows; a preset whose hash the worker does not run is computed over
``chart_history_candles + 1,000`` candles (at most 3,000) in a small thread pool, cached
15 minutes and counted against 20 a minute per user (FR-CUST-04).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from redis.exceptions import RedisError
from sqlalchemy import Connection

from tradelens.core.errors import ApiError, not_found, validation_error
from tradelens.core.keys import price_key
from tradelens.core.limits import Limits
from tradelens.core.rate_limit import enforce
from tradelens.modules.analysis.public import (
    Overlays,
    compute_overlays,
    decode_state,
    find_preset,
    htf_zones,
    instrument_analysis,
    official_rule,
    overlays_from_json,
    overlays_json,
    provisional_swings,
    series_setups,
    series_states,
    stored_overlays,
    trend_strip,
    window_overlays,
)
from tradelens.modules.market_data.public import (
    FormingCandle,
    StoredCandle,
    forming_candle,
    instrument_rows,
    load_last_candles,
    series_status_rows,
)

log = logging.getLogger("tradelens.charts")
COMPUTE_EXTRA = 1_000
COMPUTE_MAX = 3_000
CACHE_SECONDS = 900  # 15 minutes
COMPUTE_TIMEOUT_S = 30
_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="chart-compute")


@dataclass(frozen=True, slots=True)
class ChartRequest:
    """``GET /charts/{instrument}/{tf}`` parameters."""

    instrument: str
    timeframe: str
    before: datetime | None = None
    limit: int = 500
    preset: str | None = None
    profile_version_id: str | None = None
    include_inactive: bool = False


def iso(t: datetime | None) -> str | None:
    """UTC ``...Z`` or None."""
    return None if t is None else t.strftime("%Y-%m-%dT%H:%M:%SZ")


def instrument_of(conn: Connection, code: str, limits: Limits) -> dict[str, Any]:
    """The instrument row, after the asset-class check.

    Raises:
        ApiError: 404 when unknown; 403 ``plan_required`` for a commodity on Free.
    """
    row = next((r for r in instrument_rows(conn) if r["code"] == code), None)
    if row is None:
        raise not_found("Instrument not found")
    limits.require_asset(row["asset_class"])
    return row


def history_cap(limits: Limits) -> int:
    """How far back a user may scroll; a null limit (unlimited) is the compute maximum."""
    value = limits["chart_history_candles"]
    return COMPUTE_MAX if value is None else int(value)


def candle_page(
    window: Sequence[StoredCandle], before: datetime | None, limit: int
) -> tuple[list[StoredCandle], bool]:
    """One page of the capped window and whether older candles remain inside it."""
    rows = [c for c in window if before is None or c.open_time < before]
    page = list(rows[-limit:]) if limit > 0 else []
    return page, len(rows) > len(page)


def candle_json(c: StoredCandle) -> dict[str, Any]:
    """``{t, o, h, l, c, spread}`` (integers in the smallest unit)."""
    return {"t": iso(c.open_time), "o": c.o, "h": c.h, "l": c.l, "c": c.c,
            "spread": max(c.ask_c - c.bid_c, 0)}  # fmt: skip


def candles(
    conn: Connection, limits: Limits, instrument: str, timeframe: str, before: datetime | None,
    limit: int,
) -> dict[str, Any]:  # fmt: skip
    """``GET /candles/{instrument}/{tf}`` (FR-CHART-01)."""
    inst = instrument_of(conn, instrument, limits)
    cap = history_cap(limits)
    window = load_last_candles(conn, instrument, timeframe, cap)
    page, more = candle_page(window, before, min(limit, cap))
    return {"price_scale": inst["price_scale"], "candles": [candle_json(c) for c in page],
            "has_more": more}  # fmt: skip


def _status(conn: Connection, instrument: str, timeframe: str) -> dict[str, Any]:
    rows = series_status_rows(conn)
    row = next((r for r in rows if (r["instrument"], r["timeframe"]) == (instrument, timeframe)),
               None)  # fmt: skip
    if row is None:
        return {"state": "ok", "delayed_since": None, "last_candle_time": None}
    return {"state": row["status"], "delayed_since": iso(row["delayed_since"]),
            "last_candle_time": iso(row["last_candle_time"])}  # fmt: skip


FORMING_5M_LOOKBACK = 300  # 5m candles read for the forming candle (a 25-hour day is 300)


def forming_json(f: FormingCandle | None) -> dict[str, Any] | None:
    """``{t, o, h, l, c, closes_at}`` or None (integers in the smallest unit)."""
    if f is None:
        return None
    return {"t": iso(f.open_time), "o": f.o, "h": f.h, "l": f.l, "c": f.c,
            "closes_at": iso(f.closes_at)}  # fmt: skip


def _forming(
    conn: Connection, instrument: str, timeframe: str, last_closed: datetime | None,
    now: datetime,
) -> FormingCandle | None:  # fmt: skip
    """The unfinished candle for display, from stored 5m candles; None while 5m is delayed."""
    if timeframe == "5m" or _status(conn, instrument, "5m")["state"] == "delayed":
        return None
    bars = load_last_candles(conn, instrument, "5m", FORMING_5M_LOOKBACK)
    return forming_candle(timeframe, bars, last_closed, now)


def _live_price(redis: Any, instrument: str) -> dict[str, Any] | None:  # noqa: ANN401
    try:
        raw = redis.get(price_key(instrument))
    except (RedisError, OSError):
        return None
    if raw is None:
        return None
    snap = json.loads(raw)
    return {k: snap.get(k) for k in ("bid", "ask", "mid", "time", "stale")}


def _computed(
    redis: Any,  # noqa: ANN401 - redis.Redis
    key: str,
    work: Callable[[], Overlays],
) -> Overlays:
    """Cached on-demand compute (15 minutes); the engine runs in the chart thread pool."""
    try:
        raw = redis.get(key)
    except (RedisError, OSError):
        raw = None
    if raw:
        return overlays_from_json(json.loads(raw))
    future = _POOL.submit(work)
    try:
        result = future.result(timeout=COMPUTE_TIMEOUT_S)
    except FuturesTimeout as exc:
        future.cancel()  # still queued: never runs; already running: its result is dropped
        raise ApiError(503, "unavailable", "Chart is busy, try again shortly") from exc
    try:
        redis.set(key, json.dumps(overlays_json(result)), ex=CACHE_SECONDS)
    except (RedisError, OSError) as exc:
        log.warning("chart cache write failed", extra={"error": type(exc).__name__})
    return result


def chart(
    conn: Connection,
    redis: Any,  # noqa: ANN401 - redis.Redis
    limits: Limits,
    user_id: str,
    req: ChartRequest,
    *,
    custom_rate: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    """``GET /charts/{instrument}/{tf}`` (DD 4.2 chart response).

    ``forming`` is the current, unfinished candle (display only; first page only).

    Raises:
        ApiError: 404 unknown instrument; 403 ``plan_required`` (commodity on Free, or a
            profile without ``custom_settings``); 400 unknown preset; 429 over 20 custom
            charts a minute.
    """
    inst = instrument_of(conn, req.instrument, limits)
    if req.profile_version_id is not None:
        limits.require_flag("custom_settings")
        raise not_found("Profile not found")  # custom profiles arrive in task 3.7
    rule = official_rule(conn)
    settings, h, kind = rule.settings, rule.settings_hash, "official"
    if req.preset is not None:
        preset = find_preset(conn, rule, req.preset)
        if preset is None:
            raise validation_error("preset", "unknown")
        if preset.settings_hash != rule.settings_hash:
            settings, h, kind = preset.settings, preset.settings_hash, "preset"
    cap = history_cap(limits)
    depth = cap if kind == "official" else min(cap + COMPUTE_EXTRA, COMPUTE_MAX)
    base = load_last_candles(conn, req.instrument, req.timeframe, depth)
    window = base[-cap:] if cap > 0 else []
    page, more = candle_page(window, req.before, min(req.limit, cap))
    states = series_states(conn, req.instrument, rule.settings_hash)
    if kind == "official":
        state = decode_state(states.get(req.timeframe, {}).get("state"))
        ov = Overlays(state=state)
        setups: list[dict[str, Any]] = []
        if page:
            start, end = page[0].open_time, page[-1].close_time
            got = stored_overlays(conn, req.instrument, req.timeframe, h, start, end,
                                  req.include_inactive)  # fmt: skip
            ov = Overlays(got.events, got.zones, got.liquidity, state)
            setups = series_setups(conn, req.instrument, req.timeframe, h, start, end)
    else:
        enforce(redis, f"chart:{user_id}", custom_rate)
        last = iso(base[-1].open_time) if base else "none"
        key = f"chartc:{h}:{req.instrument}:{req.timeframe}:{last}:{len(base)}"
        full = _computed(redis, key, lambda: compute_overlays(
            base, req.instrument, req.timeframe, settings, rule.version))  # fmt: skip
        ov = (window_overlays(full, page[0].open_time, page[-1].close_time, req.include_inactive)
              if page else Overlays(state=full.state))  # fmt: skip
        setups = []  # setups exist only for the official settings (FR-CUST-04)
    htf = (htf_zones(conn, req.instrument, req.timeframe, rule.settings_hash,
                     page[-1].close_time) if page and limits.mtf_full else [])  # fmt: skip
    swings = [] if ov.state is None else provisional_swings(ov.state, settings, req.timeframe)
    forming = (None if req.before is not None or now is None else
               _forming(conn, req.instrument, req.timeframe,
                        base[-1].open_time if base else None, now))  # fmt: skip
    return {
        "instrument": req.instrument, "timeframe": req.timeframe,
        "price_scale": inst["price_scale"],
        "settings": {"kind": kind, "preset": req.preset or "default",
                     "profile_version_id": None, "rule_version": rule.version,
                     "settings_hash": h},
        "status": _status(conn, req.instrument, req.timeframe),
        "candles": [candle_json(c) for c in page], "has_more": more,
        "events": ov.events, "zones": ov.zones, "htf_zones": htf, "liquidity": ov.liquidity,
        "setups": setups, "trend_strip": trend_strip(states),
        "provisional": {"swings": swings}, "live_price": _live_price(redis, req.instrument),
        "forming": forming_json(forming),
    }  # fmt: skip


def parse_before(value: str | None) -> datetime | None:
    """``before`` as a UTC time (ISO with ``Z``).

    Raises:
        ApiError: 400 ``validation_error`` when not a time with a zone.
    """
    if value is None:
        return None
    try:
        t = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise validation_error("before", "invalid") from exc
    if t.tzinfo is None:
        raise validation_error("before", "timezone_required")
    return t


def analysis(
    conn: Connection, limits: Limits, instrument: str, timeframe: str, now: datetime
) -> dict[str, Any]:
    """``GET /analysis/{instrument}/{tf}`` (CR-006): read-only, same gating as charts.

    Raises:
        ApiError: 404 unknown instrument; 403 ``plan_required`` for a commodity on Free.
    """
    inst = instrument_of(conn, instrument, limits)
    return instrument_analysis(conn, inst, timeframe, now, mtf_full=limits.mtf_full)
