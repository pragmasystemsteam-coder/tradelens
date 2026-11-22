// Chart styles for the workspace (candles, hollow candles, bars, line, area, Heikin Ashi) and
// the series data each one needs. Pure functions, unit-tested in chartStyle.test.ts.

export type ChartStyle = "candles" | "hollow" | "bars" | "line" | "area" | "heikin";

export const CHART_STYLES: { value: ChartStyle; label: string }[] = [
  { value: "candles", label: "Candles" },
  { value: "hollow", label: "Hollow candles" },
  { value: "bars", label: "Bars (OHLC)" },
  { value: "line", label: "Line" },
  { value: "area", label: "Area" },
  { value: "heikin", label: "Heikin Ashi" },
];

export type Bar<T = number> = { time: T; open: number; high: number; low: number; close: number };

/** Heikin Ashi: smoothed candles. Close = OHLC average; open = mid of the previous HA body. */
export function heikinAshi<T>(bars: Bar<T>[]): Bar<T>[] {
  const out: Bar<T>[] = [];
  for (const b of bars) {
    const close = (b.open + b.high + b.low + b.close) / 4;
    const prev = out[out.length - 1];
    const open = prev ? (prev.open + prev.close) / 2 : (b.open + b.close) / 2;
    out.push({
      time: b.time,
      open,
      high: Math.max(b.high, open, close),
      low: Math.min(b.low, open, close),
      close,
    });
  }
  return out;
}

export function seriesData<T>(
  bars: Bar<T>[],
  style: ChartStyle,
): Bar<T>[] | { time: T; value: number }[] {
  if (style === "line" || style === "area")
    return bars.map((b) => ({ time: b.time, value: b.close }));
  if (style === "heikin") return heikinAshi(bars);
  return bars;
}

export function isChartStyle(v: unknown): v is ChartStyle {
  return CHART_STYLES.some((s) => s.value === v);
}
