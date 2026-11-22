"use client";

import { useEffect, useRef, useState } from "react";

import { Tip } from "@/components/ui/Tip";
import { formatTime } from "@/lib/time";
import type { SetupRow } from "@/lib/types";

import { PATTERN_LABELS } from "./Filters";

type Props = {
  rows: SetupRow[];
  delayed: string[];
  timeZone: string;
  selectedId?: string | null;
  onOpen: (row: SetupRow) => void;
  onReset?: () => void;
};

const status = (s: string) => s.charAt(0).toUpperCase() + s.slice(1).replace(/_/g, " ");

/** Ids whose combined score changed since the last render, tinted briefly. */
function useChanged(rows: SetupRow[]): Set<string> {
  const previous = useRef<Map<string, number> | null>(null);
  const [changed, setChanged] = useState<Set<string>>(new Set());
  useEffect(() => {
    const before = previous.current;
    previous.current = new Map(rows.map((r) => [r.id, r.combined]));
    if (!before) return;
    const ids = rows.filter((r) => before.has(r.id) && before.get(r.id) !== r.combined);
    if (ids.length === 0) return;
    setChanged(new Set(ids.map((r) => r.id)));
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const timer = setTimeout(() => setChanged(new Set()), reduce ? 1200 : 400);
    return () => clearTimeout(timer);
  }, [rows]);
  return changed;
}

// Ranked setups, score first. Under 768 px each row is a card (Detailed Design 5.2).
export function ScannerList({ rows, delayed, timeZone, selectedId, onOpen, onReset }: Props) {
  const changed = useChanged(rows);
  if (rows.length === 0) {
    return (
      <div className="empty" data-testid="scanner-empty" role="status">
        <strong>No confirmed setups match these filters</strong>
        <span>Try a lower minimum score, another session or the other direction.</span>
        {onReset && (
          <button type="button" className="button button--secondary" onClick={onReset}>
            Reset filters
          </button>
        )}
      </div>
    );
  }
  return (
    <ol className="scanner-list" data-testid="scanner-list">
      {rows.map((row) => {
        const classes = ["setup-row", `setup-row--${row.direction}`];
        if (row.id === selectedId) classes.push("setup-row--on");
        if (changed.has(row.id)) classes.push(`setup-row--changed-${row.direction}`);
        return (
          <li key={row.id}>
            <button
              type="button"
              className={classes.join(" ")}
              data-testid="setup-row"
              data-setup-id={row.id}
              aria-current={row.id === selectedId ? "true" : undefined}
              onClick={() => onOpen(row)}
            >
              <span className="setup-row__score" data-testid="row-combined">
                {row.combined}
              </span>
              <span className="setup-row__main">
                <strong>{row.display_name}</strong>
                <span className={`dir dir--${row.direction}`}>
                  <span aria-hidden="true">{row.direction === "bull" ? "▲" : "▼"}</span>
                  {row.direction === "bull" ? "Bullish" : "Bearish"}
                </span>
                <span className="badge">{row.timeframe.toUpperCase()}</span>
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
              <span className="setup-row__patterns">
                {row.patterns.map((p) => (
                  <span key={p} className="pattern">
                    {PATTERN_LABELS[p] ?? p.toUpperCase()}
                  </span>
                ))}
              </span>
              <span className="setup-row__meta">
                <span title="Quality">Q {row.q}</span> · <span title="Context">C {row.c}</span> ·{" "}
                {status(row.status)}, {formatTime(row.confirm_time, timeZone)}
              </span>
              <span className="setup-row__chev" aria-hidden="true">
                ›
              </span>
            </button>
          </li>
        );
      })}
      <li className="scanner-list__help">
        Q quality <Tip anchor="quality-score" label="the quality score" /> C context{" "}
        <Tip anchor="context-score" label="the context score" /> High quality{" "}
        <Tip anchor="high-quality" label="high quality" /> Counter-trend{" "}
        <Tip anchor="counter-trend" label="counter-trend" />
      </li>
    </ol>
  );
}
