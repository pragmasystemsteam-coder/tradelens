"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useMe, useReportLive } from "@/components/layout/AppShell";
import { LockIcon, WarnIcon } from "@/components/ui/Icons";
import { ProLock } from "@/components/ui/ProLock";
import { Tip } from "@/components/ui/Tip";
import { api, ApiError } from "@/lib/api";
import { formatPrice } from "@/lib/price";
import { openStream } from "@/lib/sse";
import { TIMEFRAME_LABELS, toUnixSeconds } from "@/lib/time";
import type {
  AnalysisPayload,
  ChartPayload,
  ChartTimeframe,
  Instrument,
  PatternFilter,
  SetupDetail,
} from "@/lib/types";

import { Chart, TF_SECONDS, type Tool } from "./Chart";
import { type ChartStyle } from "./chartStyle";
import {
  commit,
  type Drawing,
  historyInit,
  moveDrawing,
  redo,
  type SavedChart,
  undo,
} from "./drawings/model";
import { drawingKey, localDrawingStore } from "./drawings/store";
import { dayChange, formatCountdown, isMarketClosed, nextCloseMs, nextOpenMs } from "./market";
import type { CandidateMark, Layers, OverlayFilter } from "./Overlays";
import { TrendStrip } from "./TrendStrip";

export const TIMEFRAMES: ChartTimeframe[] = ["5m", "15m", "1h", "4h", "1d"];

export type PanelConfig = {
  instrument: string;
  timeframe: ChartTimeframe;
  style: ChartStyle;
  layers: Layers;
  preset: string;
  setupId: string | null;
};

export type PanelState = {
  count: number;
  locked: boolean;
  hidden: boolean;
  canUndo: boolean;
  canRedo: boolean;
  selected: boolean;
  label: string;
};

export type PanelHandle = {
  undo: () => void;
  redo: () => void;
  deleteSelected: () => void;
  deleteAll: () => void;
  toggleLock: () => void;
  toggleHidden: () => void;
  nudge: (bars: number, pips: number) => void;
};

type Props = {
  index: number;
  config: PanelConfig;
  active: boolean;
  compact: boolean;
  instruments: Instrument[];
  tool: Tool;
  cancelNonce: number;
  onActivate: () => void;
  onChange: (next: Partial<PanelConfig>) => void;
  onToolDone: () => void;
  onSetup: (setup: SetupDetail | null) => void;
  onState: (state: PanelState) => void;
  handleRef: (h: PanelHandle | null) => void;
  /** CR-006: patterns chosen in the scanner; the chart shows only those. */
  patternFilter?: PatternFilter | null;
  /** CR-006: scroll to an item picked in the analysis list. */
  focus?: { time: string; zoneId?: string; nonce: number } | null;
};

/** "up" or "down" for 400 ms after the live price moves, so the change is noticed. */
function useTick(mid: number | null): "up" | "down" | null {
  const last = useRef<number | null>(null);
  const [tick, setTick] = useState<"up" | "down" | null>(null);
  useEffect(() => {
    const before = last.current;
    last.current = mid;
    if (before === null || mid === null || before === mid) return;
    setTick(mid > before ? "up" : "down");
    const timer = setTimeout(() => setTick(null), 400);
    return () => clearTimeout(timer);
  }, [mid]);
  return tick;
}

/** Countdown to the candle close, or when the market reopens; ticks every second. */
function PanelClock({
  lastOpenSec,
  tfSec,
  closesAtMs,
}: {
  lastOpenSec: number | null;
  tfSec: number;
  closesAtMs: number | null;
}) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  if (isMarketClosed(now)) {
    return (
      <span className="badge badge--warn" data-testid="market-closed">
        ! Market closed · opens in {formatCountdown(nextOpenMs(now) - now)}
      </span>
    );
  }
  const close =
    closesAtMs !== null && closesAtMs > now
      ? closesAtMs
      : lastOpenSec !== null
        ? nextCloseMs(lastOpenSec, tfSec, now)
        : null;
  if (close === null) return null;
  return (
    <span className="panel-clock" title="Time to candle close" data-testid="countdown">
      closes in {formatCountdown(close - now)}
    </span>
  );
}

// One chart in the workspace: its own instrument, timeframe, style, live price and drawings
// (Detailed Design 5.2 chart page, extended for the workspace).
export function Panel(props: Props) {
  const { config, active, compact, instruments, onChange } = props;
  const { instrument, timeframe, style, layers, preset, setupId } = config;
  const me = useMe();
  const reportLive = useReportLive();
  const [payload, setPayload] = useState<ChartPayload | null>(null);
  const [setup, setSetup] = useState<SetupDetail | null>(null);
  const [locked, setLocked] = useState(false);
  const [live, setLive] = useState(true);
  const [mid, setMid] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const tick = useTick(mid);
  const [analysis, setAnalysis] = useState<AnalysisPayload | null>(null);
  const seq = useRef(0);

  // ---------------------------------------------------------------- drawings
  const key = drawingKey(me.user.id, instrument, timeframe);
  const [history, setHistory] = useState(() => historyInit([]));
  const [flags, setFlags] = useState({ locked: false, hidden: false });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const loadedKey = useRef<string | null>(null);

  useEffect(() => {
    const saved = localDrawingStore.load(key);
    loadedKey.current = key;
    setHistory(historyInit(saved.drawings));
    setFlags({ locked: saved.locked, hidden: saved.hidden });
    setSelectedId(null);
  }, [key]);

  useEffect(() => {
    if (loadedKey.current !== key) return;
    const chart: SavedChart = { v: 1, drawings: history.present, ...flags };
    localDrawingStore.save(key, chart);
  }, [history.present, flags, key]);

  const apply = useCallback((next: (cur: Drawing[]) => Drawing[]) => {
    setHistory((h) => commit(h, next(h.present)));
  }, []);

  const tfSec = TF_SECONDS[timeframe] ?? 3600;
  const scale = payload?.price_scale ?? 5;
  useEffect(() => {
    props.handleRef({
      undo: () => setHistory((h) => undo(h)),
      redo: () => setHistory((h) => redo(h)),
      deleteSelected: () => {
        if (!selectedId) return;
        apply((cur) => cur.filter((d) => d.id !== selectedId));
        setSelectedId(null);
      },
      deleteAll: () => {
        apply(() => []);
        setSelectedId(null);
      },
      toggleLock: () => setFlags((f) => ({ ...f, locked: !f.locked })),
      toggleHidden: () => setFlags((f) => ({ ...f, hidden: !f.hidden })),
      nudge: (bars, pips) => {
        if (!selectedId || flags.locked) return;
        const pip = scale >= 3 ? 10 : 1;
        apply((cur) =>
          cur.map((d) => (d.id === selectedId ? moveDrawing(d, bars * tfSec, pips * pip) : d)),
        );
      },
    });
    return () => props.handleRef(null);
    // props.handleRef is stable (created once per index by the workspace).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, flags.locked, apply, tfSec, scale]);

  const label = `${instrument.replace("_", "/")} ${TIMEFRAME_LABELS[timeframe] ?? timeframe}`;
  const { onState } = props;
  useEffect(() => {
    onState({
      count: history.present.length,
      locked: flags.locked,
      hidden: flags.hidden,
      canUndo: history.past.length > 0,
      canRedo: history.future.length > 0,
      selected: selectedId !== null,
      label,
    });
  }, [history, flags, selectedId, label, onState]);

  // ---------------------------------------------------------------- data
  const loadChart = useCallback(async () => {
    const mine = ++seq.current;
    try {
      const body = await api<ChartPayload>(`/charts/${instrument}/${timeframe}`, {
        query: { preset: preset === "default" ? undefined : preset, setup: setupId },
      });
      if (mine !== seq.current) return;
      setPayload(body);
      setMid(body.live_price?.mid ?? null);
      setLocked(false);
      setError(null);
    } catch (err) {
      if (mine !== seq.current) return;
      if (err instanceof ApiError && err.needsUpgrade) {
        setLocked(true);
        setPayload(null);
      } else if (err instanceof ApiError)
        setError(
          err.code === "rate_limited"
            ? "Too many custom charts this minute. Try again shortly."
            : err.message,
        );
      else throw err;
    }
  }, [instrument, timeframe, preset, setupId]);

  const loadSetup = useCallback(async () => {
    if (!setupId) return setSetup(null);
    try {
      setSetup(await api<SetupDetail>(`/setups/${setupId}`));
    } catch {
      setSetup(null);
    }
  }, [setupId]);

  useEffect(() => {
    setPayload(null);
    void loadChart();
  }, [loadChart]);

  useEffect(() => {
    void loadSetup();
  }, [loadSetup]);

  const { onSetup } = props;
  useEffect(() => {
    if (active) onSetup(setup);
  }, [active, setup, onSetup]);

  useEffect(() => {
    if (locked) return;
    return openStream([`chart:${instrument}`, `price:${instrument}`], {
      onEvent: (event, data) => {
        if (event === "chart.updated" && data.timeframe === timeframe) void loadChart();
        if (event === "price" && data.instrument === instrument) setMid(Number(data.mid));
        if (
          (event === "series.delayed" || event === "series.resumed") &&
          data.instrument === instrument
        )
          void loadChart();
      },
      onReconnect: () => {
        void loadChart();
        void loadSetup();
      },
      onStateChange: (connected) => {
        setLive(connected);
        reportLive(connected);
      },
    });
  }, [instrument, timeframe, locked, loadChart, loadSetup, reportLive]);

  const highlight = useMemo(() => {
    if (!payload || !setup || setup.timeframe !== timeframe || setup.instrument !== instrument)
      return null;
    const own = payload.setups.find((s) => s.id === setup.id);
    if (own) return own.zone_id;
    return (
      payload.zones.find((z) => z.low === setup.zone.low && z.high === setup.zone.high)?.id ?? null
    );
  }, [payload, setup, timeframe, instrument]);

  const change = useMemo(
    () => (payload ? dayChange(payload.candles, mid, Date.now()) : null),
    [payload, mid],
  );
  // The forming candle grows with live price ticks until its period closes; the refetch on
  // chart.updated then replaces it with the stored, finished candle.
  const forming = useMemo(() => {
    const f = payload?.forming;
    if (!f || Date.parse(f.closes_at) <= Date.now()) return null;
    if (mid === null) return f;
    return { ...f, c: mid, h: Math.max(f.h, mid), l: Math.min(f.l, mid) };
  }, [payload, mid]);
  const closesAtMs = payload?.forming ? Date.parse(payload.forming.closes_at) : null;
  const lastOpenSec = payload?.candles.length
    ? toUnixSeconds(payload.candles[payload.candles.length - 1].t)
    : null;
  // CR-006: candidates and the "All" filter come from the instrument analysis.
  useEffect(() => {
    if (locked) return setAnalysis(null);
    let live = true;
    api<AnalysisPayload>(`/analysis/${instrument}/${timeframe}`)
      .then((a) => live && setAnalysis(a))
      .catch(() => live && setAnalysis(null));
    return () => {
      live = false;
    };
  }, [instrument, timeframe, locked, payload]);

  const candidateMarks = useMemo<CandidateMark[]>(
    () =>
      (analysis?.candidates ?? []).map((c) => ({
        direction: c.direction,
        low: c.zone?.low ?? null,
        high: c.zone?.high ?? null,
        level: c.break.level,
        time: c.break.confirm_time,
      })),
    [analysis],
  );

  const { patternFilter } = props;
  const overlayFilter = useMemo<OverlayFilter>(() => {
    if (!patternFilter || patternFilter.patterns.length === 0) return null;
    const chosen = patternFilter.patterns;
    const kinds = new Set(chosen);
    const others = patternFilter.others;
    if (patternFilter.match === "any" || chosen.length < 2)
      return { kinds, zoneIds: null, windows: null, others };
    // "All": only setups and candidates with every chosen pattern, and their zones and the
    // events in the 20 candles before their break.
    const zoneIds = new Set<string>();
    const windows: [number, number][] = [];
    const span = 20 * tfSec;
    const zoneOf = new Map((payload?.setups ?? []).map((x) => [x.id, x.zone_id]));
    for (const st of analysis?.setups ?? []) {
      if (!chosen.every((p) => st.patterns.includes(p))) continue;
      const z = zoneOf.get(st.id);
      if (z) zoneIds.add(z);
      const t = toUnixSeconds(st.confirm_time);
      windows.push([t - span, t]);
    }
    for (const c of analysis?.candidates ?? []) {
      if (!chosen.every((p) => c.patterns.includes(p))) continue;
      if (c.zone) zoneIds.add(c.zone.id);
      const t = toUnixSeconds(c.break.confirm_time);
      windows.push([t - span, t]);
    }
    return { kinds, zoneIds, windows, others };
  }, [patternFilter, analysis, payload, tfSec]);

  const cap = me.entitlements.chart_history_candles;
  const name = instrument.replace("_", "/");
  const delayed = payload?.status.state === "delayed";

  return (
    <section
      className={`panel${active ? " panel--active" : ""}${compact ? " panel--compact" : ""}`}
      data-testid="panel"
      data-instrument={instrument}
      data-timeframe={timeframe}
      data-active={active ? "true" : undefined}
      aria-label={`Chart ${props.index + 1}: ${label}`}
      onPointerDownCapture={props.onActivate}
      onFocusCapture={props.onActivate}
    >
      <header className="panel-head">
        <label className="panel-symbol">
          <span className="sr-only">Instrument</span>
          <select
            aria-label={`Instrument for chart ${props.index + 1}`}
            value={instrument}
            onChange={(e) => onChange({ instrument: e.target.value, setupId: null })}
          >
            {instruments.length === 0 && <option value={instrument}>{name}</option>}
            {instruments.map((i) => (
              <option key={i.code} value={i.code}>
                {i.display_name}
                {i.available ? "" : " (Pro)"}
              </option>
            ))}
          </select>
        </label>
        <div className="panel-tfs" role="group" aria-label="Timeframe">
          {TIMEFRAMES.map((tf) => (
            <button
              key={tf}
              type="button"
              aria-pressed={tf === timeframe}
              onClick={() => onChange({ timeframe: tf, setupId: null })}
            >
              {TIMEFRAME_LABELS[tf]}
            </button>
          ))}
        </div>
        {payload && (
          <span
            className={`live-price${tick ? ` live-price--${tick}` : ""}`}
            data-testid="live-price"
          >
            {formatPrice(mid, payload.price_scale)}
            {payload.live_price?.stale ? " (stale)" : ""}
          </span>
        )}
        {change && payload && (
          <span
            className={`panel-change panel-change--${change.units >= 0 ? "up" : "down"}`}
            title="Change since the trading day's open (17:00 New York)"
          >
            {change.units >= 0 ? "+" : "−"}
            {formatPrice(Math.abs(change.units), payload.price_scale)} (
            {change.units >= 0 ? "+" : "−"}
            {Math.abs(change.percent).toFixed(2)}%)
          </span>
        )}
        {payload && !delayed && (
          <PanelClock lastOpenSec={lastOpenSec} tfSec={tfSec} closesAtMs={closesAtMs} />
        )}
        {delayed && (
          <span className="badge badge--delayed" data-testid="chart-delayed">
            Data delayed <Tip anchor="data-delayed" label="data delays" />
          </span>
        )}
        {payload && payload.settings.kind !== "official" && (
          <span className="badge">Custom settings</span>
        )}
        {style === "heikin" && (
          <span className="badge" title="Heikin Ashi candles are smoothed, not real prices">
            Heikin Ashi: smoothed, not real prices
          </span>
        )}
      </header>

      {locked ? (
        <div className="chart-area">
          <div className="chart-locked" data-testid="chart-locked">
            <span style={{ color: "var(--pro)" }}>
              <LockIcon size={28} />
            </span>
            <h2>{name} charts are on Pro</h2>
            <p className="muted">
              Pro includes metals and energy charts, full multi-timeframe detail and 2,000 candles
              of history.
            </p>
            <div className="start-card__actions" style={{ justifyContent: "center" }}>
              <Link className="button button--pro" href="/upgrade">
                See Pro
              </Link>
            </div>
          </div>
        </div>
      ) : (
        <div className="chart-area">
          {!live && (
            <div className="banner banner--warn" data-testid="reconnecting" role="status">
              <WarnIcon />
              <span>
                <strong>Reconnecting…</strong> Prices are paused until the connection is back.
              </span>
            </div>
          )}
          {error && (
            <p className="banner banner--error error" role="alert">
              <WarnIcon />
              <span>{error}</span>
            </p>
          )}
          {payload && <TrendStrip strip={payload.trend_strip} />}
          {payload ? (
            <Chart
              payload={payload}
              layers={layers}
              highlightZone={highlight}
              timeZone={me.user.timezone}
              livePrice={mid}
              forming={forming}
              patternFilter={overlayFilter}
              candidates={candidateMarks}
              focus={props.focus ?? null}
              style={style}
              drawings={history.present}
              selectedId={selectedId}
              hidden={flags.hidden}
              locked={flags.locked}
              tool={active ? props.tool : "select"}
              cancelNonce={props.cancelNonce}
              onDraw={(d) => {
                apply((cur) => [...cur, d]);
                setSelectedId(d.id);
              }}
              onChangeDrawing={(d) => apply((cur) => cur.map((x) => (x.id === d.id ? d : x)))}
              onSelect={setSelectedId}
              onToolDone={props.onToolDone}
            />
          ) : (
            <div className="skeleton chart-skeleton" aria-busy="true" aria-label="Loading chart">
              <i />
            </div>
          )}
          {/* D-ATTR: the only TradingView attribution is the library's logo inside the chart. */}
          <div className="chart-foot">
            {payload && !payload.has_more && cap < 2000 && payload.candles.length >= cap && (
              <p className="history-note" data-testid="history-cap">
                History stops at {cap} candles. Pro shows 2,000.
              </p>
            )}
          </div>
          {payload && me.entitlements.mtf_detail !== "full" && (active || !compact) && (
            <ProLock label="shows higher-timeframe zones" />
          )}
        </div>
      )}
    </section>
  );
}
