"""In-memory CandleStore for ingest unit tests (same contract as the SQL store)."""


class MemoryStore:
    def __init__(self):
        self.candles = {}  # (instrument, tf) -> {open_time: StoredCandle}
        self.status = {}
        self.gaps = []  # dicts: instrument, timeframe, gap_from, gap_to, detected_at, filled_at

    def last_open_time(self, instrument, timeframe):
        times = self.candles.get((instrument, timeframe), {})
        return max(times) if times else None

    def open_times(self, instrument, timeframe, since):
        return sorted(t for t in self.candles.get((instrument, timeframe), {}) if t >= since)

    def load(self, instrument, timeframe, since):
        rows = self.candles.get((instrument, timeframe), {})
        return [rows[t] for t in sorted(rows) if since is None or t >= since]

    def add(self, rows):
        added = 0
        for r in rows:
            bucket = self.candles.setdefault((r.instrument, r.timeframe), {})
            if r.open_time not in bucket:  # ON CONFLICT DO NOTHING: stored candles never change
                bucket[r.open_time] = r
                added += 1
        return added

    def get_status(self, instrument, timeframe):
        return self.status.get((instrument, timeframe))

    def set_status(self, instrument, timeframe, status):
        self.status[(instrument, timeframe)] = status

    def record_gap(self, instrument, timeframe, gap_from, gap_to, now):
        for g in self.gaps:
            same = (g["instrument"], g["timeframe"], g["gap_from"]) == (
                instrument,
                timeframe,
                gap_from,
            )
            if same and g["filled_at"] is None:
                g["gap_to"] = max(g["gap_to"], gap_to)
                return
        self.gaps.append(
            {
                "instrument": instrument,
                "timeframe": timeframe,
                "gap_from": gap_from,
                "gap_to": gap_to,
                "detected_at": now,
                "filled_at": None,
            }
        )

    def unfilled_gaps(self, instrument, timeframe, detected_since=None):
        return [
            (g["gap_from"], g["gap_to"])
            for g in self.gaps
            if (g["instrument"], g["timeframe"]) == (instrument, timeframe)
            and g["filled_at"] is None
            and (detected_since is None or g["detected_at"] >= detected_since)
        ]

    def fill_gap(self, instrument, timeframe, gap_from, now):
        for g in self.gaps:
            key = (g["instrument"], g["timeframe"], g["gap_from"])
            if key == (instrument, timeframe, gap_from) and g["filled_at"] is None:
                g["filled_at"] = now
