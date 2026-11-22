// Draws the user's drawings on the chart as a Lightweight Charts series primitive, like the
// SMC overlays: they scale and scroll with the chart and use the theme palette. Also maps
// between chart points (time, price units) and pane pixels for the pointer handlers.

import type {
  IChartApi,
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  ISeriesApi,
  ISeriesPrimitive,
  Logical,
  SeriesAttachedParameter,
  SeriesType,
  Time,
} from "lightweight-charts";

import type { ChartPalette } from "@/lib/theme";

import { type Drawing, fibLevels, measure, type Point, textBox } from "./model";

export type MeasureState = { a: Point; b: Point } | null;

type State = {
  drawings: Drawing[];
  draft: Drawing | null;
  measure: MeasureState;
  selectedId: string | null;
  hidden: boolean;
};

export class DrawingLayer implements ISeriesPrimitive<Time> {
  private chart: IChartApi | null = null;
  private series: ISeriesApi<SeriesType> | null = null;
  private requestUpdate: (() => void) | null = null;
  private bars: number[] = [];
  private tfSec = 3600;
  private scale = 5;
  private palette: ChartPalette | null = null;
  private state: State = {
    drawings: [],
    draft: null,
    measure: null,
    selectedId: null,
    hidden: false,
  };

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

  setData(bars: number[], tfSec: number, priceScale: number): void {
    this.bars = bars;
    this.tfSec = tfSec;
    this.scale = priceScale;
    this.requestUpdate?.();
  }

  setPalette(p: ChartPalette): void {
    this.palette = p;
    this.requestUpdate?.();
  }

  setState(next: Partial<State>): void {
    this.state = { ...this.state, ...next };
    this.requestUpdate?.();
  }

  /** Fractional bar index of a time (extrapolated beyond the data at the bar interval). */
  private logicalOf(t: number): number | null {
    const b = this.bars;
    const n = b.length;
    if (n === 0) return null;
    if (t <= b[0]) return (t - b[0]) / this.tfSec;
    if (t >= b[n - 1]) return n - 1 + (t - b[n - 1]) / this.tfSec;
    let lo = 0;
    let hi = n - 1;
    while (hi - lo > 1) {
      const mid = (lo + hi) >> 1;
      if (b[mid] <= t) lo = mid;
      else hi = mid;
    }
    return lo + (t - b[lo]) / (b[hi] - b[lo]);
  }

  private timeOf(logical: number): number {
    const b = this.bars;
    const n = b.length;
    if (logical <= 0) return Math.round(b[0] + logical * this.tfSec);
    if (logical >= n - 1) return Math.round(b[n - 1] + (logical - (n - 1)) * this.tfSec);
    const i = Math.floor(logical);
    return Math.round(b[i] + (logical - i) * (b[i + 1] - b[i]));
  }

  project = (pt: Point): { x: number; y: number } | null => {
    if (!this.chart || !this.series) return null;
    const l = this.logicalOf(pt.t);
    if (l === null) return null;
    const x = this.chart.timeScale().logicalToCoordinate(l as Logical);
    const y = this.series.priceToCoordinate(pt.p / 10 ** this.scale);
    return x === null || y === null ? null : { x, y };
  };

  unproject(x: number, y: number): Point | null {
    if (!this.chart || !this.series || this.bars.length === 0) return null;
    const l = this.chart.timeScale().coordinateToLogical(x);
    const price = this.series.coordinateToPrice(y);
    if (l === null || price === null) return null;
    return { t: this.timeOf(l), p: Math.round(price * 10 ** this.scale) };
  }

  /** Index of the bar under x (for snapping), or null. */
  barIndexAt(x: number): number | null {
    if (!this.chart) return null;
    const l = this.chart.timeScale().coordinateToLogical(x);
    if (l === null) return null;
    const i = Math.round(l);
    return i >= 0 && i < this.bars.length ? i : null;
  }

  barTime(i: number): number {
    return this.bars[i];
  }

  priceToY(units: number): number | null {
    return this.series?.priceToCoordinate(units / 10 ** this.scale) ?? null;
  }

  paneWidth(): number {
    return this.chart?.timeScale().width() ?? 0;
  }

  private fmt(units: number): string {
    return (units / 10 ** this.scale).toFixed(this.scale);
  }

  paneViews(): readonly IPrimitivePaneView[] {
    const pal = this.palette;
    const { drawings, draft, selectedId, hidden } = this.state;
    const m = this.state.measure;
    const width = this.paneWidth();
    const project = this.project;
    const renderer: IPrimitivePaneRenderer = {
      draw: (target) => {
        if (!pal) return;
        target.useMediaCoordinateSpace(({ context: ctx }) => {
          const list = hidden ? [] : drawings;
          const all = draft ? [...list, draft] : list;
          ctx.font = "11px system-ui, sans-serif";
          for (const d of all)
            this.drawOne(ctx, d, pal, width, project, d.id === selectedId || d === draft);
          if (m) this.drawMeasure(ctx, m, pal, project);
        });
      },
    };
    return [{ renderer: () => renderer }];
  }

  private drawOne(
    ctx: CanvasRenderingContext2D,
    d: Drawing,
    pal: ChartPalette,
    width: number,
    project: (pt: Point) => { x: number; y: number } | null,
    selected: boolean,
  ): void {
    const pts = d.points.map(project);
    if (pts.some((p) => !p)) return;
    const xy = pts as { x: number; y: number }[];
    const tone = d.tone === "bull" ? pal.rgb.bull : d.tone === "bear" ? pal.rgb.bear : pal.rgb.warn;
    const stroke = `rgba(${tone},0.95)`;
    ctx.strokeStyle = stroke;
    ctx.fillStyle = stroke;
    ctx.lineWidth = selected ? 2 : 1.5;
    ctx.setLineDash([]);
    const line = (x1: number, y1: number, x2: number, y2: number) => {
      ctx.beginPath();
      ctx.moveTo(x1, y1);
      ctx.lineTo(x2, y2);
      ctx.stroke();
    };
    switch (d.kind) {
      case "trend":
        line(xy[0].x, xy[0].y, xy[1].x, xy[1].y);
        break;
      case "ray": {
        const dx = xy[1].x - xy[0].x;
        const dy = xy[1].y - xy[0].y;
        const k = dx === 0 ? 0 : Math.max(1, (width - xy[0].x) / dx);
        line(
          xy[0].x,
          xy[0].y,
          dx === 0 ? xy[1].x : xy[0].x + dx * k,
          dx === 0 ? xy[1].y : xy[0].y + dy * k,
        );
        break;
      }
      case "hline":
        line(0, xy[0].y, width, xy[0].y);
        this.label(ctx, this.fmt(d.points[0].p), width - 6, xy[0].y - 4, pal, "right");
        break;
      case "rect": {
        const l = Math.min(xy[0].x, xy[1].x);
        const t = Math.min(xy[0].y, xy[1].y);
        const w = Math.abs(xy[1].x - xy[0].x);
        const h = Math.abs(xy[1].y - xy[0].y);
        ctx.fillStyle = `rgba(${tone},0.14)`;
        ctx.fillRect(l, t, w, h);
        ctx.setLineDash([4, 3]);
        ctx.strokeRect(l, t, w, h);
        ctx.setLineDash([]);
        break;
      }
      case "fib": {
        const left = Math.min(xy[0].x, xy[1].x);
        for (const lv of fibLevels(d)) {
          const y = this.priceToY(lv.p);
          if (y === null) continue;
          ctx.strokeStyle = lv.level === 0.5 || lv.level === 0.705 ? stroke : `rgba(${tone},0.6)`;
          ctx.setLineDash(lv.level === 0 || lv.level === 1 ? [] : [3, 3]);
          line(left, y, width, y);
          ctx.fillStyle = `rgba(${tone},0.95)`;
          ctx.fillText(`${lv.level} (${this.fmt(lv.p)})`, left + 4, y - 3);
        }
        ctx.setLineDash([]);
        ctx.strokeStyle = `rgba(${tone},0.5)`;
        line(xy[0].x, xy[0].y, xy[1].x, xy[1].y);
        break;
      }
      case "text": {
        const box = textBox(d.text);
        ctx.fillStyle = pal.raised;
        ctx.strokeStyle = stroke;
        ctx.beginPath();
        ctx.roundRect(xy[0].x, xy[0].y - box.h, box.w, box.h, 4);
        ctx.fill();
        ctx.stroke();
        ctx.fillStyle = pal.ink;
        ctx.fillText(d.text ?? "", xy[0].x + 7, xy[0].y - 6);
        break;
      }
    }
    if (selected && d.kind !== "hline" && d.kind !== "text") {
      for (const p of xy) {
        ctx.beginPath();
        ctx.arc(p.x, p.y, 4.5, 0, Math.PI * 2);
        ctx.fillStyle = pal.background;
        ctx.fill();
        ctx.lineWidth = 2;
        ctx.strokeStyle = stroke;
        ctx.stroke();
      }
    }
  }

  private label(
    ctx: CanvasRenderingContext2D,
    text: string,
    x: number,
    y: number,
    pal: ChartPalette,
    align: CanvasTextAlign,
  ): void {
    ctx.textAlign = align;
    ctx.fillStyle = `rgba(${pal.rgb.warn},0.95)`;
    ctx.fillText(text, x, y);
    ctx.textAlign = "left";
  }

  private drawMeasure(
    ctx: CanvasRenderingContext2D,
    m: { a: Point; b: Point },
    pal: ChartPalette,
    project: (pt: Point) => { x: number; y: number } | null,
  ): void {
    const a = project(m.a);
    const b = project(m.b);
    if (!a || !b) return;
    const r = measure(m.a, m.b, this.tfSec, this.scale);
    const tone = r.units >= 0 ? pal.rgb.bull : pal.rgb.bear;
    ctx.fillStyle = `rgba(${tone},0.14)`;
    ctx.fillRect(Math.min(a.x, b.x), Math.min(a.y, b.y), Math.abs(b.x - a.x), Math.abs(b.y - a.y));
    const text = `${r.units >= 0 ? "+" : ""}${this.fmt(r.units)} (${r.pips.toFixed(1)} pips, ${r.percent.toFixed(2)}%) · ${r.bars} bars`;
    const w = ctx.measureText(text).width + 14;
    const x = (a.x + b.x) / 2 - w / 2;
    const y = Math.min(a.y, b.y) - 26;
    ctx.fillStyle = pal.raised;
    ctx.beginPath();
    ctx.roundRect(x, y, w, 20, 4);
    ctx.fill();
    ctx.fillStyle = `rgba(${tone},1)`;
    ctx.fillText(text, x + 7, y + 14);
  }
}
