"use client";

import { Tip } from "@/components/ui/Tip";
import { formatPrice } from "@/lib/price";
import { formatTime } from "@/lib/time";
import type { AnalysisPayload } from "@/lib/types";

import { PATTERN_LABELS } from "./Filters";

export type FocusItem = { time: string; zoneId?: string; setupId?: string; label: string };

type Props = {
  data: AnalysisPayload;
  timeZone: string;
  onFocus: (item: FocusItem) => void;
};

const STATE: Record<string, string> = {
  confirmed: "Fresh",
  touched: "Touched",
  mitigated_50: "Mitigated",
  filled: "Filled",
};
const CHECK: Record<string, string> = {
  break: "Internal break (BOS or CHoCH)",
  displacement: "Displacement within the break window",
  zone_in_move: "OB or FVG inside the move",
};
const FACTOR: Record<string, string> = {
  break: "Structure break with displacement",
  sweep: "Liquidity sweep",
  fvg: "Fair value gap in the move",
  ob_fresh: "Fresh order block",
  room: "Room to opposing liquidity",
  spread_session: "Spread and session",
  htf_trend: "Higher-timeframe trend",
  htf_zone: "Inside a higher-timeframe zone",
  ltf_confirm: "Lower-timeframe confirmation",
  no_conflict: "No conflicting zone",
};
const ARROW: Record<string, string> = { bull: "▲", bear: "▼" };
const TREND: Record<string, string> = { bull: "Up", bear: "Down" };

// One instrument, computed on request (CR-006): trend, structure, zones, liquidity, every
// setup including low scores, and per direction the current candidate. Candidates are display
// only: never stored, ranked or alerted.
export function AnalysisPanel({ data, timeZone, onFocus }: Props) {
  const scale = data.price_scale;
  const name = data.instrument.replace("_", "/");
  const tf = data.timeframe.toUpperCase();
  return (
    <section className="analysis" aria-label={`Analysis: ${name} ${tf}`} data-testid="analysis">
      <div className="analysis__head">
        <h2>
          Analysis: {name} {tf}
        </h2>
        <span className="hint">Computed {formatTime(data.as_of, timeZone)}</span>
      </div>
      <div className="analysis__grid">
        <div className="analysis__card">
          <h3>Trend</h3>
          <ol className="analysis__trend">
            {data.trend_strip.map((t) => (
              <li key={t.timeframe} className={`trend trend--${t.internal}`}>
                <span className="trend__tf">{t.timeframe.toUpperCase()}</span>
                <span className="trend__dir">
                  {ARROW[t.internal] ?? "–"} {TREND[t.internal] ?? "Range"}
                </span>
              </li>
            ))}
          </ol>
        </div>

        <div className="analysis__card">
          <h3>Structure</h3>
          {data.structure.length === 0 ? (
            <p className="hint">No structure events in the last {data.recent_bars} candles.</p>
          ) : (
            <ul className="analysis__list">
              {data.structure.slice(0, 6).map((e) => (
                <li key={e.id}>
                  <button
                    type="button"
                    data-testid="analysis-item"
                    onClick={() =>
                      onFocus({ time: e.confirm_time, label: PATTERN_LABELS[e.type] ?? e.type })
                    }
                  >
                    <span className={`dir dir--${e.direction}`}>
                      {ARROW[e.direction ?? ""] ?? ""} {PATTERN_LABELS[e.type] ?? e.type}
                    </span>
                    <span>
                      {e.structure ? `${e.structure[0].toUpperCase()}${e.structure.slice(1)}` : ""}
                      {e.level !== null ? ` · ${formatPrice(e.level, scale)}` : ""}
                    </span>
                    <span className="hint">{formatTime(e.confirm_time, timeZone)}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="analysis__card">
          <h3>Open zones</h3>
          {data.zones.length === 0 ? (
            <p className="hint">No open order blocks or fair value gaps.</p>
          ) : (
            <ul className="analysis__list">
              {data.zones.slice(0, 6).map((z) => (
                <li key={z.id}>
                  <button
                    type="button"
                    data-testid="analysis-item"
                    onClick={() =>
                      onFocus({ time: z.confirm_time, zoneId: z.id, label: z.kind.toUpperCase() })
                    }
                  >
                    <span className={`dir dir--${z.direction}`}>
                      {ARROW[z.direction]} {PATTERN_LABELS[z.kind] ?? z.kind}
                    </span>
                    <span>
                      {formatPrice(z.low, scale)} – {formatPrice(z.high, scale)}
                    </span>
                    <span className="badge">{STATE[z.state] ?? z.state}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="analysis__card">
          <h3>Liquidity</h3>
          {data.liquidity.length === 0 ? (
            <p className="hint">No active liquidity levels.</p>
          ) : (
            <ul className="analysis__list analysis__list--plain">
              {data.liquidity.slice(0, 6).map((l) => (
                <li key={l.id}>
                  <span>{l.kinds.map((k) => k.replace(/_/g, " ").toUpperCase()).join(", ")}</span>
                  <span>{formatPrice(l.price, scale)}</span>
                  <span className="hint">{l.side === "buy" ? "above" : "below"}</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="analysis__card">
          <h3>Setups (all scores)</h3>
          {data.setups.length === 0 ? (
            <p className="hint">No setups in the last {data.recent_bars} candles.</p>
          ) : (
            <ul className="analysis__list">
              {data.setups.slice(0, 6).map((s) => (
                <li key={s.id}>
                  <button
                    type="button"
                    data-testid="analysis-item"
                    onClick={() =>
                      onFocus({ time: s.confirm_time, setupId: s.id, label: `Setup ${s.combined}` })
                    }
                  >
                    <span className={`score setup-score setup-score--${s.direction}`}>
                      {s.combined}
                    </span>
                    <span>
                      {ARROW[s.direction]} {s.direction === "bull" ? "Bullish" : "Bearish"}
                      {s.counter_trend ? " · Counter-trend" : ""}
                    </span>
                    <span className="hint">{formatTime(s.confirm_time, timeZone)}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {data.candidates.map((c) => (
          <div
            key={c.direction}
            className="analysis__card analysis__card--candidate"
            data-testid="candidate"
          >
            <h3>
              <span>
                {ARROW[c.direction]} {c.direction === "bull" ? "Bullish" : "Bearish"} candidate
              </span>
              <span className="badge badge--candidate">{c.label}</span>
            </h3>
            <button
              type="button"
              className="candidate__score"
              onClick={() =>
                onFocus({ time: c.break.confirm_time, zoneId: c.zone?.id, label: "Candidate" })
              }
            >
              <span className="score">{c.combined}</span>
              <span className="hint">
                would score Q {c.q}
                {c.c !== null ? ` · C ${c.c}` : ""} if it became a setup
              </span>
            </button>
            <ul className="candidate__checks">
              {c.checks.map((k) => (
                <li key={k.code} className={k.met ? "is-met" : "is-missed"}>
                  <span aria-hidden="true">{k.met ? "✓" : "✗"}</span>
                  <span>
                    <span className="sr-only">{k.met ? "Met: " : "Missed: "}</span>
                    {CHECK[k.code]}
                    {k.code === "zone_in_move" && !k.met && c.zone?.nearby
                      ? " (nearby zone used, not in the move)"
                      : ""}
                  </span>
                  <span className="hint">gate</span>
                </li>
              ))}
              {c.factors.map((f) => {
                const earned = (f.points ?? 0) > 0;
                return (
                  <li
                    key={f.code}
                    className={f.locked ? "is-locked" : earned ? "is-met" : "is-missed"}
                  >
                    <span aria-hidden="true">{f.locked ? "·" : earned ? "✓" : "✗"}</span>
                    <span>{FACTOR[f.code] ?? f.code}</span>
                    <span className="hint">{f.locked ? "Pro" : `${f.points}/${f.max}`}</span>
                  </li>
                );
              })}
            </ul>
            <p className="hint">A missed gate is why the engine made no setup here.</p>
          </div>
        ))}
      </div>
      <p className="disclaimer">
        Scores rank setups by fixed rules. They are not a probability of profit. A candidate is not
        a setup: it is never listed in the ranking or alerted.{" "}
        <Tip anchor="combined-score" label="the combined score" />
      </p>
    </section>
  );
}
