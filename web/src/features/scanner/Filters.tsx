"use client";

import { useId, useState } from "react";

import { LockBadge } from "@/components/ui/ProLock";
import { Tip } from "@/components/ui/Tip";
import type { Direction, Instrument, SetupTimeframe } from "@/lib/types";

export type ScannerFilters = {
  direction: Direction;
  timeframe: SetupTimeframe;
  instrument: string;
  assetClass: string;
  patterns: string[];
  match: "any" | "all";
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
export const PATTERN_LABELS: Record<string, string> = {
  bos: "BOS",
  choch: "CHoCH",
  sweep: "Sweep",
  fvg: "FVG",
  ob: "OB",
  displacement: "Displacement",
};
const SESSIONS = [
  { value: "asian", label: "Asian" },
  { value: "london", label: "London" },
  { value: "new_york", label: "New York" },
];

type Props = {
  value: ScannerFilters;
  onChange: (next: ScannerFilters) => void;
  onReset: () => void;
  instruments: Instrument[];
  entitledAssets: string[];
  /** Open or recent items per pattern (CR-006), shown on the chips. */
  counts?: Record<string, number> | null;
  countsLabel?: string;
};

/** How many of the refinements (the second row) differ from "any". */
export function refinementCount(f: ScannerFilters): number {
  return [f.instrument, f.patterns.length ? "x" : "", f.session, f.minScore > 0 ? "x" : ""].filter(
    Boolean,
  ).length;
}

// Everyday choices on the first row (direction, timeframe, asset class); refinements on the
// second, folded behind "Filters" on phones and in the chart page's scanner column.
export function Filters({
  value,
  onChange,
  onReset,
  instruments,
  entitledAssets,
  counts,
  countsLabel,
}: Props) {
  const [open, setOpen] = useState(false);
  const moreId = useId();
  const set = <K extends keyof ScannerFilters>(key: K, v: ScannerFilters[K]) =>
    onChange({ ...value, [key]: v });
  const count = refinementCount(value);
  return (
    <section className="filters" aria-label="Filters">
      <div className="filters__main">
        <div className="tabs" role="tablist" aria-label="Direction">
          {(["bull", "bear"] as const).map((d) => (
            <button
              key={d}
              type="button"
              role="tab"
              aria-selected={value.direction === d}
              className={`tab tab--${d}${value.direction === d ? " tab--on" : ""}`}
              onClick={() => set("direction", d)}
            >
              <span aria-hidden="true">{d === "bull" ? "▲ " : "▼ "}</span>
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
        <button
          type="button"
          className="button button--secondary filters__toggle"
          aria-expanded={open}
          aria-controls={moreId}
          onClick={() => setOpen((o) => !o)}
        >
          Filters{count > 0 ? ` · ${count}` : ""}
        </button>
        <fieldset className="asset-filter">
          <legend className="sr-only">Asset class</legend>
          <button
            type="button"
            className={value.assetClass === "" ? "chip chip--on" : "chip"}
            aria-pressed={value.assetClass === ""}
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
                aria-pressed={value.assetClass === a.value}
                disabled={locked}
                data-testid={`asset-${a.value}`}
                onClick={() => set("assetClass", a.value)}
              >
                {a.label} {locked && <LockBadge />}
              </button>
            );
          })}
        </fieldset>
      </div>
      <div className="filters__more" id={moreId} data-open={open ? "" : undefined}>
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
        <fieldset className="pattern-filter" data-testid="pattern-filter">
          <legend>Patterns</legend>
          <div className="pattern-chips">
            {Object.entries(PATTERN_LABELS).map(([p, label]) => {
              const on = value.patterns.includes(p);
              return (
                <button
                  key={p}
                  type="button"
                  className={on ? "chip chip--on" : "chip"}
                  aria-pressed={on}
                  data-pattern={p}
                  title={countsLabel}
                  onClick={() =>
                    set(
                      "patterns",
                      on ? value.patterns.filter((x) => x !== p) : [...value.patterns, p],
                    )
                  }
                >
                  {label}
                  {counts && <span className="chip__count">{counts[p] ?? 0}</span>}
                </button>
              );
            })}
            <span className="pattern-match" role="group" aria-label="Match">
              <span className="pattern-match__label">Match</span>
              {(["any", "all"] as const).map((m) => (
                <button
                  key={m}
                  type="button"
                  aria-pressed={value.match === m}
                  title={
                    m === "any"
                      ? "At least one chosen pattern"
                      : "Every chosen pattern in the same setup"
                  }
                  onClick={() => set("match", m)}
                >
                  {m === "any" ? "Any" : "All"}
                </button>
              ))}
            </span>
          </div>
        </fieldset>
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
            inputMode="numeric"
            min={0}
            max={100}
            step={5}
            value={value.minScore}
            onChange={(e) =>
              set("minScore", Math.max(0, Math.min(100, Number(e.target.value) || 0)))
            }
          />
        </label>
        {count > 0 && (
          <button type="button" className="button button--ghost" onClick={onReset}>
            Reset
          </button>
        )}
      </div>
    </section>
  );
}
