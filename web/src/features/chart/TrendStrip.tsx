import { Tip } from "@/components/ui/Tip";
import { TIMEFRAME_LABELS } from "@/lib/time";
import type { ChartPayload } from "@/lib/types";

const ARROW: Record<string, string> = { bull: "▲", bear: "▼" };
const WORD: Record<string, string> = { bull: "Up", bear: "Down" };

// Internal and external trend of all five timeframes, shown to every plan (FR-CHART-04).
// Direction is shown by arrow and word as well as colour.
export function TrendStrip({ strip }: { strip: ChartPayload["trend_strip"] }) {
  return (
    <ol className="trend-strip" data-testid="trend-strip" aria-label="Trend by timeframe">
      {strip.map((s) => (
        <li key={s.timeframe} className={`trend trend--${s.internal}`}>
          <span className="trend__tf">{TIMEFRAME_LABELS[s.timeframe] ?? s.timeframe}</span>
          <span className="trend__dir">
            <span aria-hidden="true">{ARROW[s.internal] ?? "–"} </span>
            {WORD[s.internal] ?? s.internal}
          </span>
        </li>
      ))}
      <li className="trend-strip__help">
        <Tip anchor="trend-strip" label="the trend strip" />
      </li>
    </ol>
  );
}
