import { notFound } from "next/navigation";

import { ChartPage } from "@/features/chart/ChartPage";
import { ScannerPage } from "@/features/scanner/ScannerPage";
import type { ChartTimeframe } from "@/lib/types";

const TIMEFRAMES = new Set(["5m", "15m", "1h", "4h", "1d"]);

type Props = {
  params: Promise<{ instrument: string; tf: string }>;
  searchParams: Promise<{ setup?: string }>;
};

// From 1,024 px the scanner, chart and setup panel sit side by side (Detailed Design 5.2).
export default async function Page({ params, searchParams }: Props) {
  const { instrument, tf } = await params;
  const { setup } = await searchParams;
  if (!TIMEFRAMES.has(tf) || !/^[A-Z_]{3,12}$/.test(instrument)) notFound();
  return (
    <div className="workspace">
      <aside className="workspace__scanner" aria-label="Scanner">
        <ScannerPage />
      </aside>
      <ChartPage instrument={instrument} timeframe={tf as ChartTimeframe} setupId={setup ?? null} />
    </div>
  );
}
