"""Replay recorded Twelve Data responses (tests and offline development, FR-DATA-07)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

from tradelens.integrations.twelvedata.client import parse_time_series
from tradelens.modules.market_data.ports import RawBar

SOURCE = "recorded"


class RecordedProvider:
    """Serves bars from saved ``/time_series`` bodies: ``{instrument: (file name, price scale)}``.

    Every timeframe of an instrument is served from its one recording (tests use 5m files).
    """

    name = SOURCE

    def __init__(self, directory: Path, recordings: Mapping[str, tuple[str, int]]) -> None:
        self._bars: dict[str, list[RawBar]] = {}
        for instrument, (file_name, price_scale) in recordings.items():
            doc = json.loads((directory / file_name).read_text(encoding="utf-8"))
            self._bars[instrument] = sorted(
                parse_time_series(doc, price_scale), key=lambda b: b.open_time
            )

    def source_for(self, instrument: str) -> str:
        """Value of ``candles.source`` for bars from this provider."""
        return SOURCE

    def fetch(
        self,
        instrument: str,
        timeframe: str,
        *,
        count: int,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[RawBar]:
        """Return the last ``count`` recorded bars within ``[start, end]``."""
        bars = [
            b
            for b in self._bars.get(instrument, [])
            if (start is None or b.open_time >= start) and (end is None or b.open_time <= end)
        ]
        return bars[-count:] if count > 0 else []
