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

import type { ChartPalette } from "@/lib/theme";
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
  label?: string;
  labelColor?: string;
};
type Segment = { x1: number; x2: number; y: number; color: string; dash: boolean; label: string };

const ENDED = new Set(["filled", "invalidated", "expired"]);
type Rgb = ChartPalette["rgb"];
const DEFAULT_RGB: Rgb = {
  bull: "52,198,168",
  bear: "242,115,94",
  primary: "124,176,255",
  warn: "240,164,58",
  muted: "157,174,192",
};
const rgba = (rgb: string, a: number) => `rgba(${rgb},${a})`;
const FADED = 0.22;

/** Chosen patterns (CR-006): what stays in full colour; everything else fades or hides. */
export type OverlayFilter = {
  kinds: Set<string>;
  /** "All": only zones of setups or candidates that have every chosen pattern. */
  zoneIds: Set<string> | null;
  /** "All": only events inside these [start, end] unix-second windows. */
  windows: [number, number][] | null;
  others: "fade" | "hide";
} | null;

/** A current candidate (display only): drawn dashed with a "Candidate, not a setup" label. */
export type CandidateMark = {
  direction: "bull" | "bear";
  low: number | null;
  high: number | null;
  level: number | null;
  time: string;
};

/** Whether an event of ``type`` confirmed at ``t`` (unix seconds) is chosen by the filter. */
export function eventChosen(filter: OverlayFilter, type: string, t: number): boolean {
  if (!filter) return true;
  if (!filter.kinds.has(type)) return false;
  return !filter.windows || filter.windows.some(([a, b]) => t >= a && t <= b);
}

/** Snap a UTC time to the bar that contains it (times between bars have no coordinate) */
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
  private rgb: Rgb = DEFAULT_RGB;
  private filter: OverlayFilter = null;
  private candidates: CandidateMark[] = [];

  /** Pattern filter and current candidates (CR-006). */
  setExtras(filter: OverlayFilter, candidates: CandidateMark[]): void {
    this.filter = filter;
    this.candidates = candidates;
    this.requestUpdate?.();
  }

  /** Theme colours from the CSS tokens (Chart.tsx calls this on load and on theme change). */
  setPalette(palette: ChartPalette): void {
    this.rgb = palette.rgb;
    this.requestUpdate?.();
  }

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
        const f = this.filter;
        const chosen = !f || (f.kinds.has(z.kind) && (!f.zoneIds || f.zoneIds.has(z.id))) || on;
        if (!chosen && f?.others === "hide") continue;
        const k = chosen ? 1 : FADED;
        const c = this.rgb[z.direction];
        this.boxes.push({
          x1,
          x2: Math.max(x2, x1 + 4),
          y1,
          y2,
          fill: rgba(c, (on ? 0.38 : 0.16) * k),
          stroke: rgba(c, 0.9 * k),
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
        const hChosen = !this.filter || this.filter.kinds.has(z.kind);
        if (!hChosen && this.filter?.others === "hide") continue;
        const hk = hChosen ? 1 : FADED;
        this.boxes.push({
          x1,
          x2: Math.max(x2, x1 + 4),
          y1,
          y2,
          fill: rgba(this.rgb.muted, 0.08 * hk),
          stroke: rgba(this.rgb.muted, 0.8 * hk),
          width: 1,
          dash: true,
        });
      }
    }
    // Liquidity and provisional swings are not patterns: with a filter they fade or hide.
    const other = this.filter ? (this.filter.others === "hide" ? 0 : FADED) : 1;
    if (this.layers.liquidity && other > 0) {
      for (const lv of payload.liquidity) {
        const x1 = x(lv.confirm_time);
        const x2 = x(lv.end_time);
        const yy = y(lv.price);
        if (x1 === null || x2 === null || yy === null) continue;
        const color =
          lv.side === "buy"
            ? rgba(this.rgb.primary, 0.85 * other)
            : rgba(this.rgb.warn, 0.9 * other);
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
    if (this.layers.provisional && other > 0) {
      for (const s of payload.provisional.swings) {
        const xx = x(s.origin_time);
        const yy = y(s.price);
        if (xx === null || yy === null) continue;
        this.segments.push({
          x1: xx - 12,
          x2: xx + 24,
          y: yy,
          color: rgba(this.rgb.muted, 0.9 * other),
          dash: true,
          label: "provisional",
        });
      }
    }
    // Current candidates: dashed, labelled, never mistaken for a setup.
    const right = chart.timeScale().width();
    for (const cand of this.candidates) {
      const x1 = x(cand.time);
      if (x1 === null) continue;
      const tone = rgba(this.rgb.warn, 0.95);
      if (cand.low !== null && cand.high !== null) {
        const y1 = y(cand.high);
        const y2 = y(cand.low);
        if (y1 !== null && y2 !== null) {
          this.boxes.push({
            x1,
            x2: Math.max(right, x1 + 4),
            y1,
            y2,
            fill: rgba(this.rgb.warn, 0.1),
            stroke: tone,
            width: 1.5,
            dash: true,
            label: "Candidate, not a setup",
            labelColor: tone,
          });
          continue;
        }
      }
      const yy = cand.level !== null ? y(cand.level) : null;
      if (yy !== null)
        this.segments.push({
          x1,
          x2: right,
          y: yy,
          color: tone,
          dash: true,
          label: "Candidate, not a setup",
        });
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
            if (b.label) {
              ctx.font = "600 10px sans-serif";
              ctx.fillStyle = b.labelColor ?? b.stroke;
              ctx.fillText(b.label, b.x1 + 4, Math.min(b.y1, b.y2) - 4);
            }
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
