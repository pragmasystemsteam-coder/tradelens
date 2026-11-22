"use client";

import { useCallback } from "react";

import { type ScannerHandlers, Workspace } from "@/features/chart/Workspace";
import { ScannerPage } from "@/features/scanner/ScannerPage";
import type { ChartTimeframe } from "@/lib/types";

type Props = {
  instrument: string;
  timeframe: ChartTimeframe;
  setupId: string | null;
  initialFocus?: { time: string; zoneId?: string } | null;
  initialPatterns?: { patterns: string[]; match: "any" | "all" } | null;
};

// Composes the chart workspace with the scanner for its side panel (features stay apart).
export function WorkspaceRoute(props: Props) {
  const renderScanner = useCallback(
    (h: ScannerHandlers) => (
      <ScannerPage
        onOpen={h.onOpen}
        onPatternsChange={h.onPatternsChange}
        onFocus={h.onFocus}
        initialPatterns={h.initialPatterns}
      />
    ),
    [],
  );
  return <Workspace {...props} renderScanner={renderScanner} />;
}
