"""Deterministic IDs for engine output (Detailed Design 3.8, FR-SMC-11).

Fields are joined with "|"; times as YYYY-MM-DDTHH:MM:SSZ; null as ""; the ID is the
first 32 hex characters (128 bits) of SHA-256 of the joined string.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from tradelens_engine.types import require_aware

SEP = "|"
Field = str | int | datetime | None


def _canonical(value: Field) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        raise ValueError("booleans are not ID fields")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        if SEP in value:
            raise ValueError(f"ID field may not contain {SEP!r}: {value!r}")
        return value
    if isinstance(value, datetime):
        return require_aware("time field", value).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    raise ValueError(f"unsupported ID field type {type(value).__name__}")


def make_id(*fields: Field) -> str:
    """Hash fields into a 32-hex deterministic ID (FR-SMC-11).

    Args:
        *fields: str, int, aware datetime or None, in the order of section 3.8.

    Returns:
        The first 128 bits of SHA-256 of the joined fields, as hex.

    Raises:
        ValueError: On bools, floats, naive datetimes or a "|" inside a string.
    """
    joined = SEP.join(_canonical(f) for f in fields)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:32]


def event_id(
    instrument: str,
    timeframe: str,
    type_: str,
    structure: str | None,
    direction: str | None,
    origin_time: datetime,
    confirm_time: datetime,
    level: int | None,
    settings_hash: str,
) -> str:
    """ID of a market event (FR-SMC-11); field order as in Detailed Design 3.8."""
    return make_id(
        instrument,
        timeframe,
        type_,
        structure,
        direction,
        origin_time,
        confirm_time,
        level,
        settings_hash,
    )


def zone_id(
    kind: str,
    instrument: str,
    timeframe: str,
    direction: str,
    origin_time: datetime,
    low: int,
    high: int,
    settings_hash: str,
) -> str:
    """ID of a zone: kind, instrument, timeframe, direction, origin time, low, high, hash."""
    return make_id(kind, instrument, timeframe, direction, origin_time, low, high, settings_hash)


def level_id(
    instrument: str,
    timeframe: str,
    first_kind: str,
    side: str,
    origin_time: datetime,
    price: int,
    settings_hash: str,
) -> str:
    """ID of a liquidity level (FR-SMC-07); field order as in Detailed Design 3.8."""
    return make_id(instrument, timeframe, first_kind, side, origin_time, price, settings_hash)


def setup_id(
    instrument: str,
    timeframe: str,
    profile: str,
    direction: str,
    break_event_id: str,
    settings_hash: str,
) -> str:
    """ID of a setup: instrument, timeframe, profile, direction, break event ID, hash."""
    return make_id(instrument, timeframe, profile, direction, break_event_id, settings_hash)
