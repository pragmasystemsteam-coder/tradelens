"""In-memory AnalysisStore for worker unit tests (same contract as SqlAnalysisStore)."""

import importlib.util
import json
from pathlib import Path

from tradelens.modules.analysis.scanner_cache import scanner_row
from tradelens.modules.analysis.setups import setup_to_engine_json

# The candle MemoryStore lives with the market_data tests (a sibling package, not importable
# relatively from here).
_SPEC = importlib.util.spec_from_file_location(
    "tl_memory_store", Path(__file__).parents[1] / "modules" / "market_data" / "memory_store.py"
)
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)
MemoryStore = _MOD.MemoryStore


class MemoryAnalysisStore:
    def __init__(self):
        self.states = {}  # (instrument, tf, settings_hash) -> state JSON
        self.events = {}  # id -> Event (ON CONFLICT DO NOTHING)
        self.zones = {}
        self.transitions = []
        self.saves = 0
        self.setups = {}  # id -> {"setup": Setup (latest), "asset_class": str, "revs": [Revision]}

    def load_state(self, instrument, timeframe, settings_hash):
        return self.states.get((instrument, timeframe, settings_hash))

    def load_open_setups(self, instrument, settings_hash):
        rows = [r["setup"] for r in self.setups.values()
                if r["setup"].candidate.instrument == instrument
                and r["setup"].candidate.settings_hash == settings_hash
                and r["setup"].status == "confirmed"]  # fmt: skip
        rows.sort(key=lambda s: (s.candidate.confirm_time, s.id))
        return [setup_to_engine_json(s) for s in rows]

    def _save_setups(self, batch):
        for s in batch.setups.created:
            self.setups.setdefault(s.id, {"setup": s, "asset_class": batch.asset_class,
                                          "revs": []})  # fmt: skip
        for s in batch.setups.all():
            row = self.setups[s.id]
            if s.revision > row["setup"].revision or not row["revs"]:
                row["setup"] = s
            known = {r.rev for r in row["revs"]}
            row["revs"].extend(r for r in s.revisions if r.rev not in known)

    def zone_state(self, zone_id):
        states = [s for z, s, _ in self.transitions if z == zone_id and s != "detected"]
        return states[-1] if states else "confirmed"

    def scanner_rows(self, high_quality=60):
        """``/setups`` rows of the confirmed setups, like ``load_scanner_rows``."""
        rows = []
        for r in self.setups.values():
            s = r["setup"]
            if s.status != "confirmed":
                continue
            c = s.candidate
            zone = self.zones[s.primary_zone_id]
            rows.append(scanner_row({
                "id": s.id, "instrument": c.instrument, "display_name": c.instrument,
                "asset_class": r["asset_class"], "price_scale": s.price_scale,
                "timeframe": c.timeframe, "profile": c.profile, "direction": c.direction,
                "patterns": c.patterns, "sessions": c.sessions, "q": s.q, "c": s.c,
                "combined": s.combined, "counter_trend": s.counter_trend,
                "zone_low": zone.low, "zone_high": zone.high,
                "zone_state": self.zone_state(zone.id), "invalidation": c.invalidation,
                "spread": c.spread, "status": s.status, "confirm_time": c.confirm_time,
            }, high_quality))  # fmt: skip
        return rows

    def save_batch(self, batch):
        self.saves += 1
        self._save_setups(batch)
        for tf, outs in batch.result.outputs.items():
            for out in outs:
                for e in out.events:
                    self.events.setdefault(e.id, e)
                for z in out.new_zones:
                    self.zones.setdefault(z.id, z)
                self.transitions.extend(out.zone_transitions)
            if outs:
                state = batch.result.states[tf]
                self.states[(batch.instrument, tf, batch.settings_hash)] = state.to_json()

    def event_ids(self, timeframe=None):
        return sorted(e.id for e in self.events.values() if timeframe in (None, e.timeframe))


class MemoryUnitOfWork:
    """``transaction()`` for CloseJob: the shared candle store and analysis store."""

    def __init__(self, candles, analysis):
        self.candles, self.analysis = candles, analysis

    def __call__(self):
        return self

    def __enter__(self):
        return self.candles, self.analysis

    def __exit__(self, *exc):
        return False


class RecordingRedis:
    def __init__(self):
        self.published = []  # (channel, dict)
        self.values = {}

    def publish(self, channel, message):
        self.published.append((channel, json.loads(message)))
        return 1

    def set(self, name, value, ex=None):
        self.values[name] = value
        return True

    def get(self, name):
        return self.values.get(name)

    def events(self, name):
        return [(ch, m["data"]) for ch, m in self.published if m["event"] == name]
