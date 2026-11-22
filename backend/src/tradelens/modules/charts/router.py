"""``GET /charts/{instrument}/{tf}`` and ``GET /candles/{instrument}/{tf}`` (DD 4.2; task 2.6)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Connection

from tradelens.core.config import AppConfig
from tradelens.core.deps import Viewer, get_clock, get_config, get_conn, get_redis, get_viewer
from tradelens.modules.charts.service import ChartRequest, analysis, candles, chart, parse_before

router = APIRouter(prefix="/api/v1", tags=["charts"])
Timeframe = Literal["5m", "15m", "1h", "4h", "1d"]


@router.get("/charts/{instrument}/{timeframe}")
def get_chart(
    instrument: str,
    timeframe: Timeframe,
    *,
    before: Annotated[str | None, Query(max_length=40)] = None,
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
    preset: Annotated[str | None, Query(max_length=20)] = None,
    profile_version_id: Annotated[str | None, Query(max_length=64)] = None,
    include_inactive: Annotated[int, Query(ge=0, le=1)] = 0,
    setup: Annotated[str | None, Query(max_length=32)] = None,
    viewer: Annotated[Viewer, Depends(get_viewer)],
    conn: Annotated[Connection, Depends(get_conn, scope="function")],
    redis: Annotated[Any, Depends(get_redis)],  # noqa: ANN401 - redis.Redis
    cfg: Annotated[AppConfig, Depends(get_config)],
    clock: Annotated[Callable[[], datetime], Depends(get_clock)],
) -> dict[str, Any]:
    """Candles with overlays, trend strip, provisional swings and the live price.

    ``forming`` is the current, unfinished candle for display only.

    ``setup`` only tells the browser which zone to highlight; the payload is the same.
    """
    del setup
    req = ChartRequest(instrument, timeframe, parse_before(before), limit, preset,
                       profile_version_id, bool(include_inactive))  # fmt: skip
    return chart(conn, redis, viewer.limits, viewer.user_id, req,
                 custom_rate=cfg.rate_custom_chart, now=clock())  # fmt: skip


@router.get("/candles/{instrument}/{timeframe}")
def get_candles(
    instrument: str,
    timeframe: Timeframe,
    *,
    before: Annotated[str | None, Query(max_length=40)] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 500,
    viewer: Annotated[Viewer, Depends(get_viewer)],
    conn: Annotated[Connection, Depends(get_conn, scope="function")],
) -> dict[str, Any]:
    """Raw candles, never beyond ``chart_history_candles`` (FR-CHART-01)."""
    return candles(conn, viewer.limits, instrument, timeframe, parse_before(before), limit)


@router.get("/analysis/{instrument}/{timeframe}")
def get_analysis(
    instrument: str,
    timeframe: Timeframe,
    *,
    viewer: Annotated[Viewer, Depends(get_viewer)],
    conn: Annotated[Connection, Depends(get_conn, scope="function")],
    clock: Annotated[Callable[[], datetime], Depends(get_clock)],
) -> dict[str, Any]:
    """Instrument analysis with candidates (CR-006); candidates are display only."""
    return analysis(conn, viewer.limits, instrument, timeframe, clock())
