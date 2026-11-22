import { notFound } from "next/navigation";

import type { ChartTimeframe } from "@/lib/types";

import { WorkspaceRoute } from "./WorkspaceRoute";

const KNOWN_PATTERNS = new Set(["bos", "choch", "sweep", "fvg", "ob", "displacement"]);
const TIMEFRAMES = new Set(["5m", "15m", "1h", "4h", "1d"]);

type Props = {
  params: Promise<{ instrument: string; tf: string }>;
  searchParams: Promise<{
    setup?: string;
    focus?: string;
    zone?: string;
    patterns?: string;
    match?: string;
  }>;
};

// From 1,024 px the scanner and chart sit side by side, from 1,366 px the setup panel too.
export default async function Page({ params, searchParams }: Props) {
  const { instrument, tf } = await params;
  const { setup, focus, zone, patterns, match } = await searchParams;
  const chosen = (patterns ?? "").split(",").filter((p) => KNOWN_PATTERNS.has(p));
  if (!TIMEFRAMES.has(tf) || !/^[A-Z_]{3,12}$/.test(instrument)) notFound();
  return (
    <WorkspaceRoute
      instrument={instrument}
      timeframe={tf as ChartTimeframe}
      setupId={setup ?? null}
      initialFocus={focus ? { time: focus, zoneId: zone } : null}
      initialPatterns={
        chosen.length ? { patterns: chosen, match: match === "all" ? "all" : "any" } : null
      }
    />
  );
}
