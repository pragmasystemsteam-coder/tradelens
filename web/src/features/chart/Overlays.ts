// Chart overlays drawn as a Lightweight Charts series primitive (AD-14): zone boxes, higher-
// timeframe zones, liquidity lines and provisional swings. Prices are integers; they are
// divided by 10^price_scale here, for drawing only.

import type {
  IChartApi,
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  ISeriesApi,
  ISeriesPrimitive,
  SeriesAttachedParameter,
  SeriesType,
  Time,
  UTCTimestamp,
} from "lightweight-charts";

import { toUnixSeconds } from "@/lib/time";
import type { ChartPayload } from "@/lib/types";

export type Layers = {
  structure: boolean;
  zones: boolean;
  liquidity: boolean;
  provisional: boolean;
};

type Box = {
  x1: number;
  x2: number;
  y1: number;
  y2: number;
  fill: string;
  stroke: string;
  width: number;
  dash: boolean;
};
type Segment = { x1: number; x2: number; y: number; color: string; dash: boolean; label: string };

const ENDED = new Set(["filled", "invalidated", "expired"]);
const COLORS = {
  bull: { fill: "rgba(38,166,154,0.16)", stroke: "rgba(38,166,154,0.9)" },
  bear: { fill: "rgba(239,83,80,0.16)", stroke: "rgba(239,83,80,0.9)" },
};

/** Snap a UTC time to the bar that contains it (times between bars have no coordinate). */
export function snap(bars: number[], t: number): number {
  if (bars.length === 0) return t;
  let lo = 0;
  let hi = bars.length - 1;
  if (t <= bars[0]) return bars[0];
  if (t >= bars[hi]) return bars[hi];
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (bars[mid] <= t) lo = mid;
    else hi = mid - 1;
  }
  return bars[lo];
}

export class OverlayPrimitive implements ISeriesPrimitive<Time> {
  private chart: IChartApi | null = null;
  private series: ISeriesApi<SeriesType> | null = null;
  private requestUpdate: (() => void) | null = null;
  private payload: ChartPayload | null = null;
  private layers: Layers = { structure: true, zones: true, liquidity: true, provisional: true };
  private highlight: string | null = null;
  private boxes: Box[] = [];
  private segments: Segment[] = [];

  attached(param: SeriesAttachedParameter<Time>): void {
    this.chart = param.chart as IChartApi;
    this.series = param.series;
    this.requestUpdate = param.requestUpdate;
  }

  detached(): void {
    this.chart = null;
    this.series = null;
    this.requestUpdate = null;
  }

  set(payload: ChartPayload, layers: Layers, highlight: string | null): void {
    this.payload = payload;
    this.layers = layers;
    this.highlight = highlight;
    this.requestUpdate?.();
  }

  updateAllViews(): void {
    this.boxes = [];
    this.segments = [];
    const { chart, series, payload } = this;
    if (!chart || !series || !payload || payload.candles.length === 0) return;
    const scale = 10 ** payload.price_scale;
    const bars = payload.candles.map((c) => toUnixSeconds(c.t));
    const last = bars[bars.length - 1];
    const x = (iso: string | null | undefined) => {
      const t = iso ? snap(bars, toUnixSeconds(iso)) : last;
      return chart.timeScale().timeToCoordinate(t as UTCTimestamp);
    };
    const y = (units: number) => series.priceToCoordinate(units / scale);
    if (this.layers.zones) {
      for (const z of payload.zones) {
        const x1 = x(z.confirm_time);
        const x2 = x(ENDED.has(z.state) ? z.state_time : null);
        const y1 = y(z.high);
        const y2 = y(z.low);
        if (x1 === null || x2 === null || y1 === null || y2 === null) continue;
        const on = z.id === this.highlight;
        const c = COLORS[z.direction];
        this.boxes.push({
          x1,
          x2: Math.max(x2, x1 + 4),
          y1,
          y2,
          fill: on ? c.fill.replace("0.16", "0.38") : c.fill,
          stroke: c.stroke,
          width: on ? 3 : 1,
          dash: false,
        });
      }
      for (const z of payload.htf_zones) {
        const y1 = y(z.high);
        const y2 = y(z.low);
        const x1 = x(z.confirm_time);
        const x2 = x(null);
        if (x1 === null || x2 === null || y1 === null || y2 === null) continue;
        this.boxes.push({
          x1,
          x2: Math.max(x2, x1 + 4),
          y1,
          y2,
          fill: "rgba(120,120,160,0.08)",
          stroke: "rgba(120,120,160,0.8)",
          width: 1,
          dash: true,
        });
      }
    }
    if (this.layers.liquidity) {
      for (const lv of payload.liquidity) {
        const x1 = x(lv.confirm_time);
        const x2 = x(lv.end_time);
        const yy = y(lv.price);
        if (x1 === null || x2 === null || yy === null) continue;
        const color = lv.side === "buy" ? "rgba(41,98,255,0.85)" : "rgba(255,152,0,0.9)";
        this.segments.push({
          x1,
          x2,
          y: yy,
          color,
          dash: lv.status === "ended",
          label: lv.kinds[0] ?? "",
        });
      }
    }
    if (this.layers.provisional) {
      for (const s of payload.provisional.swings) {
        const xx = x(s.origin_time);
        const yy = y(s.price);
        if (xx === null || yy === null) continue;
        this.segments.push({
          x1: xx - 12,
          x2: xx + 24,
          y: yy,
          color: "rgba(90,90,90,0.9)",
          dash: true,
          label: "provisional",
        });
      }
    }
  }

  paneViews(): readonly IPrimitivePaneView[] {
    const boxes = this.boxes;
    const segments = this.segments;
    const renderer: IPrimitivePaneRenderer = {
      draw: (target) => {
        target.useMediaCoordinateSpace(({ context: ctx }) => {
          for (const b of boxes) {
            ctx.fillStyle = b.fill;
            ctx.fillRect(b.x1, Math.min(b.y1, b.y2), b.x2 - b.x1, Math.abs(b.y2 - b.y1));
            ctx.strokeStyle = b.stroke;
            ctx.lineWidth = b.width;
            ctx.setLineDash(b.dash ? [4, 3] : []);
            ctx.strokeRect(b.x1, Math.min(b.y1, b.y2), b.x2 - b.x1, Math.abs(b.y2 - b.y1));
          }
          ctx.font = "10px sans-serif";
          for (const s of segments) {
            ctx.strokeStyle = s.color;
            ctx.lineWidth = 1;
            ctx.setLineDash(s.dash ? [5, 4] : []);
            ctx.beginPath();
            ctx.moveTo(s.x1, s.y);
            ctx.lineTo(s.x2, s.y);
            ctx.stroke();
            ctx.fillStyle = s.color;
            ctx.fillText(s.label, s.x1 + 2, s.y - 3);
          }
          ctx.setLineDash([]);
        });
      },
    };
    return [{ renderer: () => renderer }];
  }
}
