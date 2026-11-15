"use client";

import { Tip } from "@/components/ui/Tip";
import { formatTime } from "@/lib/time";
import type { SetupRow } from "@/lib/types";

type Props = {
  rows: SetupRow[];
  delayed: string[];
  timeZone: string;
  selectedId?: string;
  onOpen: (row: SetupRow) => void;
};

// Ranked setups; under 768 px each row is a two-line card (Detailed Design 5.2).
export function ScannerList({ rows, delayed, timeZone, selectedId, onOpen }: Props) {
  if (rows.length === 0) {
    return (
      <p className="empty" data-testid="scanner-empty">
        No confirmed setups match these filters
      </p>
    );
  }
  return (
    <ol className="scanner-list" data-testid="scanner-list">
      {rows.map((row) => (
        <li key={row.id}>
          <button
            type="button"
            className={row.id === selectedId ? "setup-row setup-row--on" : "setup-row"}
            data-testid="setup-row"
            data-setup-id={row.id}
            onClick={() => onOpen(row)}
          >
            <span className="setup-row__main">
              <strong>{row.display_name}</strong>
              <span className={`dir dir--${row.direction}`}>
                {row.direction === "bull" ? "Bullish" : "Bearish"}
              </span>
              <span className="tf">{row.timeframe.toUpperCase()}</span>
              {row.high_quality && (
                <span className="badge badge--hq" title="Combined score 60 or more">
                  High quality
                </span>
              )}
              {row.counter_trend && (
                <span className="badge badge--warn" title="Against the higher-timeframe trend">
                  Counter-trend
                </span>
              )}
              {delayed.includes(row.instrument) && (
                <span className="badge badge--delayed" data-testid="row-delayed">
                  Data delayed
                </span>
              )}
            </span>
            <span className="setup-row__scores">
              <span title="Quality">Q {row.q}</span>
              <span title="Context">C {row.c}</span>
              <span className="combined" data-testid="row-combined">
                {row.combined}
              </span>
            </span>
            <span className="setup-row__meta">
              {row.patterns.map((p) => p.toUpperCase()).join(" · ")} · {row.status} ·{" "}
              {formatTime(row.confirm_time, timeZone)}
            </span>
          </button>
        </li>
      ))}
      <li className="scanner-list__help">
        Q <Tip anchor="quality-score" label="the quality score" /> C{" "}
        <Tip anchor="context-score" label="the context score" /> High quality{" "}
        <Tip anchor="high-quality" label="high quality" /> Counter-trend{" "}
        <Tip anchor="counter-trend" label="counter-trend" />
      </li>
    </ol>
  );
}
