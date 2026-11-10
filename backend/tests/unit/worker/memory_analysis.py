"""In-memory AnalysisStore for worker unit tests (same contract as SqlAnalysisStore)."""

import importlib.util
import json
from pathlib import Path

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

    def load_state(self, instrument, timeframe, settings_hash):
        return self.states.get((instrument, timeframe, settings_hash))

    def save_batch(self, batch):
        self.saves += 1
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
