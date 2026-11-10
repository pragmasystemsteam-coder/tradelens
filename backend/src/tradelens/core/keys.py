"""Redis key and channel names shared by the worker and the API (DD 4.4, 4.8; task 1.9).

They live in ``core`` because both roots need them and neither may import the other.
"""

from __future__ import annotations

HEARTBEAT_KEY = "worker:heartbeat"  # Unix time of the last beat, TTL 15 s
PRICE_STREAM_KEY = "worker:prices"  # Unix time of the last price tick handled
DATA_CHANNEL = "data"  # series.delayed / series.resumed
SCANNER_CHANNEL = "updates:scanner"


def price_key(instrument: str) -> str:
    """Snapshot key of the latest price of ``instrument``."""
    return f"price:{instrument}"


def prices_channel(instrument: str) -> str:
    """Pub/sub channel of price ticks for ``instrument`` (at most every 500 ms)."""
    return f"prices:{instrument}"


def updates_channel(instrument: str) -> str:
    """Pub/sub channel of chart updates for ``instrument``."""
    return f"updates:{instrument}"
