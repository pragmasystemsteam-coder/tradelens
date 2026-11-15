"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { useMe } from "@/components/layout/AppShell";
import { ProLock } from "@/components/ui/ProLock";
import { Tip } from "@/components/ui/Tip";
import { api, ApiError } from "@/lib/api";
import { formatPrice } from "@/lib/price";
import { openStream } from "@/lib/sse";
import { TIMEFRAME_LABELS } from "@/lib/time";
import type { ChartPayload, ChartTimeframe, SetupDetail } from "@/lib/types";

import { Chart } from "./Chart";
import type { Layers } from "./Overlays";
import { SetupPanel } from "./SetupPanel";
import { TrendStrip } from "./TrendStrip";

const TIMEFRAMES: ChartTimeframe[] = ["5m", "15m", "1h", "4h", "1d"];
const PRESETS = ["default", "scalping", "intraday", "swing"];
const LAYER_NAMES: { key: keyof Layers; label: string }[] = [
  { key: "structure", label: "Structure" },
  { key: "zones", label: "Zones" },
  { key: "liquidity", label: "Liquidity" },
  { key: "provisional", label: "Provisional" },
];

type Props = { instrument: string; timeframe: ChartTimeframe; setupId: string | null };

export function ChartPage({ instrument, timeframe, setupId }: Props) {
  const me = useMe();
  const [payload, setPayload] = useState<ChartPayload | null>(null);
  const [setup, setSetup] = useState<SetupDetail | null>(null);
  const [locked, setLocked] = useState(false);
  const [preset, setPreset] = useState("default");
  const [layers, setLayers] = useState<Layers>({
    structure: true,
    zones: true,
    liquidity: true,
    provisional: true,
  });
  const [live, setLive] = useState(true);
  const [mid, setMid] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const presetRef = useRef(preset);
  presetRef.current = preset;

  const seq = useRef(0);

  // Only the newest request may paint (preset or timeframe changes while one is in flight).
  const loadChart = useCallback(async () => {
    const mine = ++seq.current;
    try {
      const body = await api<ChartPayload>(`/charts/${instrument}/${timeframe}`, {
        query: {
          preset: presetRef.current === "default" ? undefined : presetRef.current,
          setup: setupId,
        },
      });
      if (mine !== seq.current) return;
      setPayload(body);
      setMid(body.live_price?.mid ?? null);
      setLocked(false);
      setError(null);
    } catch (err) {
      if (mine !== seq.current) return;
      if (err instanceof ApiError && err.needsUpgrade) setLocked(true);
      else if (err instanceof ApiError)
        setError(
          err.code === "rate_limited"
            ? "Too many custom charts this minute. Try again shortly."
            : err.message,
        );
      else throw err;
    }
  }, [instrument, timeframe, setupId]);

  const loadSetup = useCallback(async () => {
    if (!setupId) return setSetup(null);
    try {
      setSetup(await api<SetupDetail>(`/setups/${setupId}`));
    } catch {
      setSetup(null);
    }
  }, [setupId]);

  useEffect(() => {
    void loadChart();
  }, [loadChart, preset]);

  useEffect(() => {
    void loadSetup();
  }, [loadSetup]);

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
      onStateChange: setLive,
    });
  }, [instrument, timeframe, locked, loadChart, loadSetup]);

  if (locked) {
    return (
      <div className="chart-page" data-testid="chart-locked">
        <ProLock label="includes metals and energy charts" />
      </div>
    );
  }
  const highlight =
    setup?.timeframe === timeframe && setup.instrument === instrument
      ? zoneOf(payload, setup)
      : null;
  const cap = me.entitlements.chart_history_candles;
  return (
    <div className="chart-page">
      {!live && (
        <div className="banner banner--warn" data-testid="reconnecting">
          Reconnecting…
        </div>
      )}
      <section className="chart-area">
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <header className="chart-head">
          <h1>{payload?.instrument.replace("_", "/") ?? instrument}</h1>
          {payload && (
            <span className="live-price" data-testid="live-price">
              {formatPrice(mid, payload.price_scale)}
              {payload.live_price?.stale ? " (stale)" : ""}
              {payload.live_price && ` · spread ${payload.live_price.ask - payload.live_price.bid}`}
            </span>
          )}
          {payload?.status.state === "delayed" && (
            <span className="badge badge--delayed" data-testid="chart-delayed">
              Data delayed <Tip anchor="data-delayed" label="data delays" />
            </span>
          )}
          {payload && payload.settings.kind !== "official" && (
            <span className="badge">Custom settings</span>
          )}
        </header>
        <div className="chart-tools">
          <nav className="tf-buttons" aria-label="Timeframe">
            {TIMEFRAMES.map((tf) => (
              <Link
                key={tf}
                href={`/chart/${instrument}/${tf}`}
                aria-current={tf === timeframe ? "page" : undefined}
                className={tf === timeframe ? "chip chip--on" : "chip"}
              >
                {TIMEFRAME_LABELS[tf]}
              </Link>
            ))}
          </nav>
          <label>
            Preset
            <select name="preset" value={preset} onChange={(e) => setPreset(e.target.value)}>
              {PRESETS.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </label>
          <fieldset className="layers">
            <legend>Layers</legend>
            {LAYER_NAMES.map((l) => (
              <label key={l.key}>
                <input
                  type="checkbox"
                  checked={layers[l.key]}
                  onChange={(e) => setLayers({ ...layers, [l.key]: e.target.checked })}
                />
                {l.label}
              </label>
            ))}
            <Tip anchor="provisional" label="provisional swings" />
          </fieldset>
        </div>
        {payload && <TrendStrip strip={payload.trend_strip} />}
        {payload && (
          <Chart
            payload={payload}
            layers={layers}
            highlightZone={highlight}
            timeZone={me.user.timezone}
            livePrice={mid}
          />
        )}
        <p className="attribution">
          <a href="https://www.tradingview.com/" target="_blank" rel="noreferrer">
            Charts by TradingView
          </a>
        </p>
        {payload && me.entitlements.mtf_detail !== "full" && (
          <ProLock label="shows higher-timeframe zones" />
        )}
        {payload && !payload.has_more && cap < 2000 && payload.candles.length >= cap && (
          <p className="history-note" data-testid="history-cap">
            History stops at {cap} candles. Pro shows 2,000.
          </p>
        )}
      </section>
      {setup && <SetupPanel setup={setup} timeZone={me.user.timezone} />}
    </div>
  );
}

function zoneOf(payload: ChartPayload | null, setup: SetupDetail): string | null {
  if (!payload) return null;
  const own = payload.setups.find((s) => s.id === setup.id);
  if (own) return own.zone_id;
  const match = payload.zones.find((z) => z.low === setup.zone.low && z.high === setup.zone.high);
  return match?.id ?? null;
}
