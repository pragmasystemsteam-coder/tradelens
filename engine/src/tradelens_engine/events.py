"""Engine output records: market events and zones (DD 2.5 columns, 3.1, 3.8 IDs).

:class:`SeriesKey` carries what every output row of one series shares (instrument, timeframe,
rule version, settings hash) and builds the deterministic IDs of section 3.8.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from tradelens_engine.ids import event_id, level_id, zone_id
from tradelens_engine.timefmt import iso

EventType = Literal["swing_high", "swing_low", "bos", "choch", "sweep", "breakout", "displacement"]
StructureName = Literal["internal", "external"]
Pairs = tuple[tuple[str, Any], ...]


@dataclass(frozen=True, slots=True)
class Event:
    """A ``market_events`` row. ``level`` is the swing price or the broken/swept level.

    ``details`` and ``refs`` are ``(key, value)`` pairs (hashable) written to the JSON columns.
    A displacement has no level (DB check ``type = 'displacement' AND level IS NULL``).
    """

    id: str
    instrument: str
    timeframe: str
    type: EventType
    structure: StructureName | None
    direction: str | None
    level: int | None
    origin_time: datetime
    confirm_time: datetime
    settings_hash: str
    rule_version: str
    details: Pairs = ()
    refs: Pairs = ()

    def to_json(self) -> dict[str, Any]:
        """Plain JSON form (times as ISO-8601 UTC)."""
        return {
            "id": self.id, "instrument": self.instrument, "timeframe": self.timeframe,
            "type": self.type, "structure": self.structure, "direction": self.direction,
            "level": self.level, "origin_time": iso(self.origin_time),
            "confirm_time": iso(self.confirm_time), "settings_hash": self.settings_hash,
            "rule_version": self.rule_version, "details": dict(self.details),
            "refs": dict(self.refs),
        }  # fmt: skip


@dataclass(frozen=True, slots=True)
class Zone:
    """A ``zones`` row at creation: an FVG, or an order block at its promotion (FR-SMC-10)."""

    id: str
    kind: Literal["fvg", "ob"]
    instrument: str
    timeframe: str
    direction: str
    low: int
    high: int
    origin_time: datetime
    confirm_time: datetime
    settings_hash: str
    rule_version: str
    pre_confirmation_touch: bool = False
    source_event_id: str | None = None

    def to_json(self) -> dict[str, Any]:
        """Plain JSON form (times as ISO-8601 UTC)."""
        return {
            "id": self.id, "kind": self.kind, "instrument": self.instrument,
            "timeframe": self.timeframe, "direction": self.direction, "low": self.low,
            "high": self.high, "origin_time": iso(self.origin_time),
            "confirm_time": iso(self.confirm_time), "settings_hash": self.settings_hash,
            "rule_version": self.rule_version,
            "pre_confirmation_touch": self.pre_confirmation_touch,
            "source_event_id": self.source_event_id,
        }  # fmt: skip


@dataclass(frozen=True, slots=True)
class SeriesKey:
    """What every output row of one series shares, plus the ID builders (DD 3.8)."""

    instrument: str
    timeframe: str
    rule_version: str
    settings_hash: str

    def event(
        self, type_: EventType, structure: StructureName | None, direction: str | None,
        level: int | None, origin: datetime, confirm: datetime, *, details: Pairs = (),
        refs: Pairs = (),
    ) -> Event:  # fmt: skip
        """Build an event with its deterministic ID."""
        eid = event_id(
            self.instrument, self.timeframe, type_, structure, direction, origin, confirm,
            level, self.settings_hash,
        )  # fmt: skip
        return Event(
            eid, self.instrument, self.timeframe, type_, structure, direction, level, origin,
            confirm, self.settings_hash, self.rule_version, details, refs,
        )  # fmt: skip

    def zone_id(self, kind: str, direction: str, origin: datetime, low: int, high: int) -> str:
        """Zone ID: kind, instrument, timeframe, direction, origin time, low, high, hash."""
        return zone_id(
            kind, self.instrument, self.timeframe, direction, origin, low, high,
            self.settings_hash,
        )  # fmt: skip

    def level_id(self, first_kind: str, side: str, origin: datetime, price: int) -> str:
        """Level ID: instrument, timeframe, first kind, side, origin time, price, hash."""
        return level_id(
            self.instrument, self.timeframe, first_kind, side, origin, price, self.settings_hash
        )
