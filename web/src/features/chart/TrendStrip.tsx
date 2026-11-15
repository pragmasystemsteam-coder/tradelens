import { Tip } from "@/components/ui/Tip";
import { TIMEFRAME_LABELS } from "@/lib/time";
import type { ChartPayload } from "@/lib/types";

// Internal and external trend of all five timeframes, shown to every plan (FR-CHART-04).
export function TrendStrip({ strip }: { strip: ChartPayload["trend_strip"] }) {
  return (
    <ol className="trend-strip" data-testid="trend-strip" aria-label="Trend by timeframe">
      {strip.map((s) => (
        <li key={s.timeframe} className={`trend trend--${s.internal}`}>
          <span className="trend__tf">{TIMEFRAME_LABELS[s.timeframe] ?? s.timeframe}</span>
          <span className="trend__dir">{s.internal}</span>
        </li>
      ))}
      <li className="trend-strip__help">
        <Tip anchor="trend-strip" label="the trend strip" />
      </li>
    </ol>
  );
}
