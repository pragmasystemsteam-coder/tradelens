"use client";

import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useMe, useReportLive } from "@/components/layout/AppShell";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { WarnIcon } from "@/components/ui/Icons";
import { api } from "@/lib/api";
import { openStream } from "@/lib/sse";
import { formatTime } from "@/lib/time";
import type {
  AnalysisPayload,
  Instrument,
  PatternFilter,
  SetupRow,
  SetupsPage,
  SetupTimeframe,
} from "@/lib/types";

import { AnalysisPanel, type FocusItem } from "./AnalysisPanel";
import { Filters, type ScannerFilters } from "./Filters";
import { ScannerList } from "./ScannerList";

const STYLE_TF: Record<string, SetupTimeframe> = { scalping: "15m", intraday: "1h", swing: "4h" };

type Props = {
  /** In the chart workspace: load the setup into the active chart instead of changing page. */
  onOpen?: (row: SetupRow) => void;
  /** In the chart workspace: the chosen patterns, so the chart shows only those (CR-006). */
  onPatternsChange?: (filter: Pick<PatternFilter, "patterns" | "match">) => void;
  /** In the chart workspace: scroll the active chart to an analysis item. */
  onFocus?: (item: FocusItem & { instrument: string; timeframe: string }) => void;
  /** Patterns chosen before opening the chart (from the address). */
  initialPatterns?: Pick<PatternFilter, "patterns" | "match"> | null;
};

export function ScannerPage({ onOpen, onPatternsChange, onFocus, initialPatterns }: Props = {}) {
  const me = useMe();
  const router = useRouter();
  const pathname = usePathname();
  const reportLive = useReportLive();
  const defaults = useMemo<ScannerFilters>(
    () => ({
      direction: "bull",
      timeframe: STYLE_TF[me.user.trading_style] ?? "1h",
      instrument: "",
      assetClass: "",
      patterns: [],
      match: "any",
      session: "",
      minScore: 0,
    }),
    [me.user.trading_style],
  );
  const [filters, setFilters] = useState<ScannerFilters>(() => ({
    ...defaults,
    ...(initialPatterns ?? {}),
  }));
  const [page, setPage] = useState<SetupsPage | null>(null);
  const [analysis, setAnalysis] = useState<AnalysisPayload | null>(null);
  const [failed, setFailed] = useState(false);
  const [instruments, setInstruments] = useState<Instrument[]>([]);
  const [live, setLive] = useState(true);
  const [selected, setSelected] = useState<string | null>(null);
  const filtersRef = useRef(filters);
  filtersRef.current = filters;

  const seq = useRef(0);

  // Only the newest request may set the list: a slower older answer (for example the
  // "6" typed before "60") must not overwrite it.
  const load = useCallback(async () => {
    const f = filtersRef.current;
    const mine = ++seq.current;
    try {
      const next = await api<SetupsPage>("/setups", {
        query: {
          direction: f.direction,
          timeframe: f.timeframe,
          instrument: f.instrument ? [f.instrument] : undefined,
          asset_class: f.assetClass,
          pattern: f.patterns.length ? f.patterns : undefined,
          match: f.patterns.length > 1 ? f.match : undefined,
          session: f.session ? [f.session] : undefined,
          min_score: f.minScore || undefined,
          limit: 100,
        },
      });
      if (mine === seq.current) {
        setPage(next);
        setFailed(false);
      }
    } catch {
      if (mine === seq.current) setFailed(true);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [filters, load]);

  useEffect(() => {
    void api<{ items: Instrument[] }>("/instruments").then((r) => setInstruments(r.items));
  }, []);

  // On the chart page the open setup is in the address; highlight its row.
  useEffect(() => {
    setSelected(new URLSearchParams(window.location.search).get("setup"));
  }, [pathname]);

  useEffect(
    () =>
      openStream(["scanner"], {
        onEvent: (event, data) => {
          if (event === "scanner.updated" && data.timeframe === filtersRef.current.timeframe)
            void load();
          if (event === "series.delayed" || event === "series.resumed") void load();
        },
        onReconnect: () => void load(),
        onStateChange: (connected) => {
          setLive(connected);
          reportLive(connected);
        },
      }),
    [load, reportLive],
  );

  const open = useCallback(
    (row: SetupRow) => {
      setSelected(row.id);
      if (onOpen) onOpen(row);
      else router.push(`/chart/${row.instrument}/${row.timeframe}?setup=${row.id}`);
    },
    [router, onOpen],
  );
  const reset = useCallback(() => setFilters(defaults), [defaults]);
  const asOf = useMemo(
    () => formatTime(page?.data_as_of, me.user.timezone),
    [page, me.user.timezone],
  );

  // One instrument chosen: analyse it on request, even without a setup (CR-006).
  useEffect(() => {
    if (!filters.instrument) {
      setAnalysis(null);
      return;
    }
    let live = true;
    api<AnalysisPayload>(`/analysis/${filters.instrument}/${filters.timeframe}`)
      .then((a) => live && setAnalysis(a))
      .catch(() => live && setAnalysis(null));
    return () => {
      live = false;
    };
  }, [filters.instrument, filters.timeframe, page]);

  useEffect(() => {
    onPatternsChange?.({ patterns: filters.patterns, match: filters.match });
  }, [filters.patterns, filters.match, onPatternsChange]);

  const counts = useMemo(() => {
    if (analysis) return analysis.pattern_counts;
    if (!page) return null;
    const out: Record<string, number> = {};
    for (const row of page.items) for (const p of row.patterns) out[p] = (out[p] ?? 0) + 1;
    return out;
  }, [analysis, page]);

  const focus = useCallback(
    (item: FocusItem) => {
      const target = { ...item, instrument: filters.instrument, timeframe: filters.timeframe };
      if (onFocus) return onFocus(target);
      const q = new URLSearchParams({ focus: item.time });
      if (item.zoneId) q.set("zone", item.zoneId);
      if (item.setupId) q.set("setup", item.setupId);
      if (filters.patterns.length) {
        q.set("patterns", filters.patterns.join(","));
        q.set("match", filters.match);
      }
      router.push(`/chart/${filters.instrument}/${filters.timeframe}?${q.toString()}`);
    },
    [filters.instrument, filters.timeframe, filters.patterns, filters.match, onFocus, router],
  );

  return (
    <div className="scanner-page">
      <div className="page-head">
        <h1>Scanner</h1>
        <p className="data-time" data-testid="data-as-of">
          Data as of {asOf}
        </p>
      </div>
      {!live && (
        <div className="banner banner--warn" data-testid="reconnecting" role="status">
          <WarnIcon />
          <span>
            <strong>Reconnecting…</strong> Live updates are paused. The list refreshes as soon as
            the connection is back.
          </span>
        </div>
      )}
      <Filters
        value={filters}
        onChange={setFilters}
        onReset={reset}
        instruments={instruments}
        entitledAssets={me.entitlements.asset_classes}
        counts={counts}
        countsLabel={
          analysis
            ? `Open or recent in the last ${analysis.recent_bars} candles`
            : "Setups in this list"
        }
      />
      <Disclaimer />
      {analysis && <AnalysisPanel data={analysis} timeZone={me.user.timezone} onFocus={focus} />}
      {failed && (
        <div className="banner banner--error" role="alert">
          <WarnIcon />
          <span>
            Couldn&apos;t load setups. Check your connection, then try again.{" "}
            <button type="button" className="link-button" onClick={() => void load()}>
              Try again
            </button>
          </span>
        </div>
      )}
      {page ? (
        <ScannerList
          rows={page.items}
          delayed={page.series_delayed}
          timeZone={me.user.timezone}
          selectedId={selected}
          onOpen={open}
          onReset={reset}
        />
      ) : (
        !failed && (
          <div className="skeleton" aria-busy="true" aria-label="Loading setups">
            <i />
            <i />
            <i />
            <i />
          </div>
        )
      )}
    </div>
  );
}
