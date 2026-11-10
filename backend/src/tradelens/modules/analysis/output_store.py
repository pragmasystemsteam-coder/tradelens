"""PostgreSQL ``AnalysisStore``: engine state and output of a close batch (DD 2.5, task 1.9).

Everything of one batch is written on the caller's connection, so events, zones, transitions,
liquidity levels and ``series_state`` commit together or not at all. Rows are insert-only with
deterministic IDs (``ON CONFLICT DO NOTHING``), so re-processing after a crash or a rebuild is
harmless (FR-SMC-11). Zones change only their lifecycle columns; levels only their kinds
(a second kind joins, never leaves) and end fields - the guards in migrations 0001/0002 enforce it.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from sqlalchemy import Connection, text

from tradelens.modules.analysis.process import CloseBatch
from tradelens_engine.events import Event, Zone
from tradelens_engine.rules.liquidity import Level, LevelChange
from tradelens_engine.series import STATE_VERSION

INSERT_EVENT = text(
    "INSERT INTO market_events (id, instrument, timeframe, settings_hash, rule_version, type,"
    " structure, direction, level, details, origin_time, confirm_time, refs)"
    " VALUES (:id, :instrument, :timeframe, :settings_hash, :rule_version, :type, :structure,"
    " :direction, :level, CAST(:details AS jsonb), :origin_time, :confirm_time,"
    " CAST(:refs AS jsonb)) ON CONFLICT (id) DO NOTHING"
)
INSERT_ZONE = text(
    "INSERT INTO zones (id, kind, instrument, timeframe, settings_hash, rule_version, direction,"
    " low, high, origin_time, confirm_time, state, state_time, pre_confirmation_touch,"
    " source_event_id) VALUES (:id, :kind, :instrument, :timeframe, :settings_hash,"
    " :rule_version, :direction, :low, :high, :origin_time, :confirm_time, 'confirmed',"
    " :confirm_time, :pre_confirmation_touch, :source_event_id) ON CONFLICT (id) DO NOTHING"
)
INSERT_TRANSITION = text(
    "INSERT INTO zone_transitions (zone_id, state, candle_time) VALUES (:zone_id, :state, :t)"
    " ON CONFLICT DO NOTHING"
)
UPDATE_ZONE = text(
    "UPDATE zones SET state = :state, state_time = :t, retests = COALESCE(:retests, retests)"
    " WHERE id = :id"
)
INSERT_LEVEL = text(
    "INSERT INTO liquidity_levels (id, instrument, timeframe, settings_hash, rule_version, kinds,"
    " side, price, structure, origin_time, confirm_time) VALUES (:id, :instrument, :timeframe,"
    " :settings_hash, :rule_version, :kinds, :side, :price, :structure, :origin_time,"
    " :confirm_time) ON CONFLICT (id) DO NOTHING"
)
UPDATE_LEVEL_KINDS = text(
    "UPDATE liquidity_levels SET kinds = :kinds WHERE id = :id AND end_time IS NULL"
    " AND kinds IS DISTINCT FROM CAST(:kinds AS text[])"
)
END_LEVEL = text(
    "UPDATE liquidity_levels SET end_time = :end_time, end_reason = :end_reason,"
    " ended_by = :ended_by WHERE id = :id AND end_time IS NULL"
)
UPSERT_STATE = text(
    "INSERT INTO series_state (instrument, timeframe, settings_hash, rule_version, engine_schema,"
    " state, trend_internal, trend_external, as_of, updated_at) VALUES (:instrument, :timeframe,"
    " :settings_hash, :rule_version, :schema, CAST(:state AS jsonb), :ti, :te, :as_of, now())"
    " ON CONFLICT (instrument, timeframe, settings_hash) DO UPDATE SET"
    " rule_version = EXCLUDED.rule_version, engine_schema = EXCLUDED.engine_schema,"
    " state = EXCLUDED.state, trend_internal = EXCLUDED.trend_internal,"
    " trend_external = EXCLUDED.trend_external, as_of = EXCLUDED.as_of, updated_at = now()"
)
LOAD_STATE = text(
    "SELECT state FROM series_state WHERE instrument = :i AND timeframe = :tf"
    " AND settings_hash = :h"
)


def _event_row(e: Event) -> dict[str, Any]:
    return {
        "id": e.id, "instrument": e.instrument, "timeframe": e.timeframe,
        "settings_hash": e.settings_hash, "rule_version": e.rule_version, "type": e.type,
        "structure": e.structure, "direction": e.direction, "level": e.level,
        "details": json.dumps(dict(e.details)), "origin_time": e.origin_time,
        "confirm_time": e.confirm_time, "refs": json.dumps(dict(e.refs)),
    }  # fmt: skip


def _zone_row(z: Zone) -> dict[str, Any]:
    return {
        "id": z.id, "kind": z.kind, "instrument": z.instrument, "timeframe": z.timeframe,
        "settings_hash": z.settings_hash, "rule_version": z.rule_version,
        "direction": z.direction, "low": z.low, "high": z.high, "origin_time": z.origin_time,
        "confirm_time": z.confirm_time, "pre_confirmation_touch": z.pre_confirmation_touch,
        "source_event_id": z.source_event_id,
    }  # fmt: skip


def _level_row(lv: Level) -> dict[str, Any]:
    return {
        "id": lv.id, "instrument": lv.instrument, "timeframe": lv.timeframe,
        "settings_hash": lv.settings_hash, "rule_version": lv.rule_version,
        "kinds": list(lv.kinds), "side": lv.side, "price": lv.price, "structure": lv.structure,
        "origin_time": lv.origin_time, "confirm_time": lv.confirm_time,
    }  # fmt: skip


class SqlAnalysisStore:
    """AnalysisStore over one open connection (the caller owns the transaction)."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def load_state(
        self, instrument: str, timeframe: str, settings_hash: str
    ) -> Mapping[str, Any] | None:
        """The saved state JSON, or None."""
        row = self._conn.execute(
            LOAD_STATE, {"i": instrument, "tf": timeframe, "h": settings_hash}
        ).first()
        return None if row is None else dict(row[0])

    def _levels(self, changes: list[LevelChange]) -> None:
        for ch in changes:  # in emission order: a level is created before it is updated or ended
            lv = ch.level
            if ch.change == "created":
                self._conn.execute(INSERT_LEVEL, _level_row(lv))
            if ch.change in ("created", "updated"):
                self._conn.execute(UPDATE_LEVEL_KINDS, {"id": lv.id, "kinds": list(lv.kinds)})
            if lv.end_time is not None:
                self._conn.execute(END_LEVEL, {"id": lv.id, "end_time": lv.end_time,
                                               "end_reason": lv.end_reason,
                                               "ended_by": lv.ended_by})  # fmt: skip

    def save_batch(self, batch: CloseBatch) -> None:
        """Write the whole batch on this connection (one transaction with the caller's commit).

        Args:
            batch: The processed close batch of one instrument.
        """
        res = batch.result
        events, zones, transitions, levels = [], [], [], []
        for tf in res.outputs:
            for out in res.outputs[tf]:
                events += [_event_row(e) for e in out.events]
                zones += [_zone_row(z) for z in out.new_zones]
                transitions += list(out.zone_transitions)
                levels += list(out.level_changes)
        if events:
            self._conn.execute(INSERT_EVENT, events)
        if zones:
            self._conn.execute(INSERT_ZONE, zones)
        if transitions:
            self._conn.execute(
                INSERT_TRANSITION, [{"zone_id": z, "state": s, "t": t} for z, s, t in transitions]
            )
        self._zone_states(batch, transitions)
        self._levels(levels)
        self._states(batch)

    def _zone_states(self, batch: CloseBatch, transitions: list[tuple[str, str, Any]]) -> None:
        latest: dict[str, tuple[str, Any]] = {}
        for zid, state, t in transitions:
            if state != "detected":
                latest[zid] = (state, t)
        retests = {zs.zone.id: zs.retests for st in batch.result.states.values()
                   for zs in st.zones}  # fmt: skip
        rows = [{"id": zid, "state": s, "t": t, "retests": retests.get(zid)}
                for zid, (s, t) in latest.items()]  # fmt: skip
        if rows:
            self._conn.execute(UPDATE_ZONE, rows)

    def _states(self, batch: CloseBatch) -> None:
        rows = []
        for tf, outs in batch.result.outputs.items():
            if not outs:
                continue
            st = batch.result.states[tf]
            rows.append({
                "instrument": batch.instrument, "timeframe": tf,
                "settings_hash": batch.settings_hash, "rule_version": batch.rule_version,
                "schema": STATE_VERSION, "state": json.dumps(st.to_json()),
                "ti": st.internal.trend, "te": st.external.trend, "as_of": st.last_close_time,
            })  # fmt: skip
        if rows:
            self._conn.execute(UPSERT_STATE, rows)
