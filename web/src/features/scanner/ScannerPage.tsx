"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useMe } from "@/components/layout/AppShell";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { api } from "@/lib/api";
import { openStream } from "@/lib/sse";
import { formatTime } from "@/lib/time";
import type { Instrument, SetupRow, SetupsPage, SetupTimeframe } from "@/lib/types";

import { Filters, type ScannerFilters } from "./Filters";
import { ScannerList } from "./ScannerList";

const STYLE_TF: Record<string, SetupTimeframe> = { scalping: "15m", intraday: "1h", swing: "4h" };

export function ScannerPage() {
  const me = useMe();
  const router = useRouter();
  const [filters, setFilters] = useState<ScannerFilters>({
    direction: "bull",
    timeframe: STYLE_TF[me.user.trading_style] ?? "1h",
    instrument: "",
    assetClass: "",
    pattern: "",
    session: "",
    minScore: 0,
  });
  const [page, setPage] = useState<SetupsPage | null>(null);
  const [instruments, setInstruments] = useState<Instrument[]>([]);
  const [live, setLive] = useState(true);
  const filtersRef = useRef(filters);
  filtersRef.current = filters;

  const seq = useRef(0);

  // Only the newest request may set the list: a slower older answer (for example the
  // "6" typed before "60") must not overwrite it.
  const load = useCallback(async () => {
    const f = filtersRef.current;
    const mine = ++seq.current;
    const next = await api<SetupsPage>("/setups", {
      query: {
        direction: f.direction,
        timeframe: f.timeframe,
        instrument: f.instrument ? [f.instrument] : undefined,
        asset_class: f.assetClass,
        pattern: f.pattern ? [f.pattern] : undefined,
        session: f.session ? [f.session] : undefined,
        min_score: f.minScore || undefined,
        limit: 100,
      },
    });
    if (mine === seq.current) setPage(next);
  }, []);

  useEffect(() => {
    void load();
  }, [filters, load]);

  useEffect(() => {
    void api<{ items: Instrument[] }>("/instruments").then((r) => setInstruments(r.items));
  }, []);

  useEffect(
    () =>
      openStream(["scanner"], {
        onEvent: (event, data) => {
          if (event === "scanner.updated" && data.timeframe === filtersRef.current.timeframe)
            void load();
          if (event === "series.delayed" || event === "series.resumed") void load();
        },
        onReconnect: () => void load(),
        onStateChange: setLive,
      }),
    [load],
  );

  const open = useCallback(
    (row: SetupRow) => router.push(`/chart/${row.instrument}/${row.timeframe}?setup=${row.id}`),
    [router],
  );
  const asOf = useMemo(
    () => formatTime(page?.data_as_of, me.user.timezone),
    [page, me.user.timezone],
  );

  return (
    <div className="scanner-page">
      {!live && (
        <div className="banner banner--warn" data-testid="reconnecting">
          Reconnecting…
        </div>
      )}
      <Filters
        value={filters}
        onChange={setFilters}
        instruments={instruments}
        entitledAssets={me.entitlements.asset_classes}
      />
      <Disclaimer />
      <p className="data-time" data-testid="data-as-of">
        Data as of {asOf}
      </p>
      {page && (
        <ScannerList
          rows={page.items}
          delayed={page.series_delayed}
          timeZone={me.user.timezone}
          onOpen={open}
        />
      )}
    </div>
  );
}
