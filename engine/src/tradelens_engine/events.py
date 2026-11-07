"""Engine output records: market events and zones (DD 2.5 columns, 3.1, 3.8 IDs)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from tradelens_engine.timefmt import iso

EventType = Literal["swing_high", "swing_low", "bos", "choch"]
StructureName = Literal["internal", "external"]


@dataclass(frozen=True, slots=True)
class Event:
    """A ``market_events`` row. ``level`` is the swing price or the broken level."""

    id: str
    instrument: str
    timeframe: str
    type: EventType
    structure: StructureName
    direction: str | None
    level: int
    origin_time: datetime
    confirm_time: datetime
    settings_hash: str
    rule_version: str

    def to_json(self) -> dict[str, Any]:
        """Plain JSON form (times as ISO-8601 UTC)."""
        return {
            "id": self.id, "instrument": self.instrument, "timeframe": self.timeframe,
            "type": self.type, "structure": self.structure, "direction": self.direction,
            "level": self.level, "origin_time": iso(self.origin_time),
            "confirm_time": iso(self.confirm_time), "settings_hash": self.settings_hash,
            "rule_version": self.rule_version,
        }  # fmt: skip


@dataclass(frozen=True, slots=True)
class Zone:
    """A ``zones`` row at creation (Day 2: FVGs; order blocks follow in task 1.6)."""

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

    def to_json(self) -> dict[str, Any]:
        """Plain JSON form (times as ISO-8601 UTC)."""
        return {
            "id": self.id, "kind": self.kind, "instrument": self.instrument,
            "timeframe": self.timeframe, "direction": self.direction, "low": self.low,
            "high": self.high, "origin_time": iso(self.origin_time),
            "confirm_time": iso(self.confirm_time), "settings_hash": self.settings_hash,
            "rule_version": self.rule_version,
        }  # fmt: skip
