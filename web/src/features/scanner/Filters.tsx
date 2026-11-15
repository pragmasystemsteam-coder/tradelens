"use client";

import { LockBadge } from "@/components/ui/ProLock";
import { Tip } from "@/components/ui/Tip";
import type { Direction, Instrument, SetupTimeframe } from "@/lib/types";

export type ScannerFilters = {
  direction: Direction;
  timeframe: SetupTimeframe;
  instrument: string;
  assetClass: string;
  pattern: string;
  session: string;
  minScore: number;
};

const TIMEFRAMES: { value: SetupTimeframe; label: string }[] = [
  { value: "15m", label: "15m Scalping" },
  { value: "1h", label: "1H Intraday" },
  { value: "4h", label: "4H Swing" },
];
const ASSETS = [
  { value: "forex", label: "Forex" },
  { value: "metal", label: "Metals" },
  { value: "energy", label: "Energy" },
];
const PATTERNS = ["bos", "choch", "sweep", "fvg", "ob", "displacement"];
const SESSIONS = [
  { value: "asian", label: "Asian" },
  { value: "london", label: "London" },
  { value: "new_york", label: "New York" },
];

type Props = {
  value: ScannerFilters;
  onChange: (next: ScannerFilters) => void;
  instruments: Instrument[];
  entitledAssets: string[];
};

export function Filters({ value, onChange, instruments, entitledAssets }: Props) {
  const set = <K extends keyof ScannerFilters>(key: K, v: ScannerFilters[K]) =>
    onChange({ ...value, [key]: v });
  return (
    <section className="filters" aria-label="Filters">
      <div className="tabs" role="tablist" aria-label="Direction">
        {(["bull", "bear"] as const).map((d) => (
          <button
            key={d}
            type="button"
            role="tab"
            aria-selected={value.direction === d}
            className={value.direction === d ? "tab tab--on" : "tab"}
            onClick={() => set("direction", d)}
          >
            {d === "bull" ? "Bullish" : "Bearish"}
          </button>
        ))}
      </div>
      <label>
        Timeframe <Tip anchor="timeframes" label="timeframes and profiles" />
        <select
          name="timeframe"
          value={value.timeframe}
          onChange={(e) => set("timeframe", e.target.value as SetupTimeframe)}
        >
          {TIMEFRAMES.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </select>
      </label>
      <label>
        Instrument
        <select
          name="instrument"
          value={value.instrument}
          onChange={(e) => set("instrument", e.target.value)}
        >
          <option value="">All</option>
          {instruments.map((i) => (
            <option key={i.code} value={i.code} disabled={!i.available}>
              {i.display_name}
              {i.available ? "" : " (Pro)"}
            </option>
          ))}
        </select>
      </label>
      <fieldset className="asset-filter">
        <legend>Asset class</legend>
        <button
          type="button"
          className={value.assetClass === "" ? "chip chip--on" : "chip"}
          onClick={() => set("assetClass", "")}
        >
          All
        </button>
        {ASSETS.map((a) => {
          const locked = !entitledAssets.includes(a.value);
          return (
            <button
              key={a.value}
              type="button"
              className={value.assetClass === a.value ? "chip chip--on" : "chip"}
              disabled={locked}
              data-testid={`asset-${a.value}`}
              onClick={() => set("assetClass", a.value)}
            >
              {a.label} {locked && <LockBadge />}
            </button>
          );
        })}
      </fieldset>
      <label>
        Pattern
        <select
          name="pattern"
          value={value.pattern}
          onChange={(e) => set("pattern", e.target.value)}
        >
          <option value="">Any</option>
          {PATTERNS.map((p) => (
            <option key={p} value={p}>
              {p.toUpperCase()}
            </option>
          ))}
        </select>
      </label>
      <label>
        Session <Tip anchor="sessions" label="sessions" />
        <select
          name="session"
          value={value.session}
          onChange={(e) => set("session", e.target.value)}
        >
          <option value="">Any</option>
          {SESSIONS.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>
      </label>
      <label>
        Minimum score <Tip anchor="combined-score" label="the combined score" />
        <input
          name="min_score"
          type="number"
          min={0}
          max={100}
          step={5}
          value={value.minScore}
          onChange={(e) => set("minScore", Math.max(0, Math.min(100, Number(e.target.value) || 0)))}
        />
      </label>
    </section>
  );
}
