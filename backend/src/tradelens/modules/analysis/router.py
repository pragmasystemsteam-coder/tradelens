"""Development-only chart routes (DD 8.1 task 1.10). Mounted only when APP_ENV=development.

``GET /dev/chart`` serves the Lightweight Charts page; ``GET /dev/chart/data`` runs the engine
over the stored candles of one series. Thin: the work is in ``chart_data.py``.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Literal, Protocol

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse

from tradelens.modules.analysis.public import chart_payload
from tradelens.modules.market_data.public import StoredCandle
from tradelens_engine.settings import Settings

PAGE = Path(__file__).with_name("dev_chart.html")
HISTORY = 3000  # candles run through the engine (warm-up) before the last 500 are shown

router = APIRouter(prefix="/dev", tags=["development"])


class ChartSource(Protocol):
    """Stored candles and display data for the dev chart (wired in ``app.bootstrap``)."""

    @property
    def settings(self) -> Settings:
        """Settings of the active rule version."""
        ...

    @property
    def rule_version(self) -> str:
        """The active rule version."""
        ...

    def candles(self, instrument: str, timeframe: str) -> Sequence[StoredCandle]:
        """Stored candles of one series, oldest first."""
        ...

    def price_scale(self, instrument: str) -> int | None:
        """Decimal places of the instrument, None when unknown."""
        ...


def get_chart_source() -> ChartSource:
    """Dependency placeholder; ``tradelens.app.bootstrap.wire`` supplies the database source.

    Raises:
        RuntimeError: Always, if the app was built without wiring.
    """
    raise RuntimeError("dev chart source is not wired; build the app with create_app()")


@router.get("/chart", response_class=HTMLResponse)
def dev_chart_page() -> HTMLResponse:
    """The chart page (loads data from ``/dev/chart/data``)."""
    return HTMLResponse(PAGE.read_text(encoding="utf-8"))


@router.get("/chart/data")
def dev_chart_data(
    source: Annotated[ChartSource, Depends(get_chart_source)],
    instrument: Annotated[str, Query(min_length=3, max_length=16)],
    timeframe: Annotated[Literal["5m", "15m", "1h", "4h", "1d"], Query()] = "1h",
) -> JSONResponse:
    """Candles and overlays of one series."""
    scale = source.price_scale(instrument)
    if scale is None:
        raise HTTPException(status_code=404, detail="unknown instrument")
    rows = list(source.candles(instrument, timeframe))[-HISTORY:]
    payload = chart_payload(rows, instrument, timeframe, source.settings, source.rule_version,
                            price_scale=scale)  # fmt: skip
    return JSONResponse(payload)
