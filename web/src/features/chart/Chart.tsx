"use client";

import {
  AreaSeries,
  BarSeries,
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  LineSeries,
  LineStyle,
  type SeriesMarker,
  type SeriesType,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import { type PointerEvent as ReactPointerEvent, useEffect, useRef, useState } from "react";

import { type ChartPalette, onThemeChange, readChartPalette } from "@/lib/theme";
import { axisLabel, toUnixSeconds } from "@/lib/time";
import type { ChartPayload } from "@/lib/types";

import { type ChartStyle, seriesData } from "./chartStyle";
import { DrawingLayer, type MeasureState } from "./drawings/DrawingLayer";
import {
  createDrawing,
  type Drawing,
  type DrawingKind,
  hitTest,
  moveDrawing,
  moveHandle,
  type Point,
  POINTS_NEEDED,
} from "./drawings/model";
import {
  type CandidateMark,
  eventChosen,
  type Layers,
  type OverlayFilter,
  OverlayPrimitive,
  snap,
} from "./Overlays";

export type Tool = "select" | "measure" | DrawingKind;

export const TF_SECONDS: Record<string, number> = {
  "5m": 300,
  "15m": 900,
  "1h": 3600,
  "4h": 14_400,
  "1d": 86_400,
};

type Props = {
  payload: ChartPayload;
  layers: Layers;
  highlightZone: string | null;
  timeZone: string;
  livePrice: number | null;
  /** The unfinished candle (display only), drawn faded after the last finished one. */
  forming: { t: string; o: number; h: number; l: number; c: number } | null;
  style: ChartStyle;
  drawings: Drawing[];
  selectedId: string | null;
  hidden: boolean;
  locked: boolean;
  tool: Tool;
  /** Changes when Esc is pressed: cancels a drawing in progress, a measure or a note. */
  cancelNonce: number;
  /** CR-006: chosen patterns stay in full colour; the rest fade or hide. */
  patternFilter?: OverlayFilter;
  /** CR-006: current candidates, drawn dashed with a label (display only). */
  candidates?: CandidateMark[];
  /** Scroll to this time and flash the zone, when ``nonce`` changes. */
  focus?: { time: string; zoneId?: string; nonce: number } | null;
  onDraw: (d: Drawing) => void;
  onChangeDrawing: (d: Drawing) => void;
  onSelect: (id: string | null) => void;
  onToolDone: () => void;
};

const MARKED = new Set(["bos", "choch", "sweep"]);
const SNAP_PX = 6;

function markers(
  payload: ChartPayload,
  palette: ChartPalette,
  filter: OverlayFilter = null,
): SeriesMarker<Time>[] {
  const bars = payload.candles.map((c) => toUnixSeconds(c.t));
  const tfSeconds = bars.length > 1 ? bars[1] - bars[0] : 3600;
  return payload.events
    .filter((e) => MARKED.has(e.type))
    .filter(
      (e) =>
        filter?.others !== "hide" || eventChosen(filter, e.type, toUnixSeconds(e.confirm_time)),
    )
    .map((e) => {
      const bull = e.direction === "bull";
      const label =
        e.type === "sweep"
          ? "sweep"
          : `${e.type.toUpperCase()}${e.structure === "external" ? " ext" : ""}`;
      return {
        time: snap(bars, toUnixSeconds(e.confirm_time) - tfSeconds) as UTCTimestamp,
        position: bull ? "belowBar" : "aboveBar",
        shape: e.type === "sweep" ? "circle" : bull ? "arrowUp" : "arrowDown",
        color: eventChosen(filter, e.type, toUnixSeconds(e.confirm_time))
          ? bull
            ? palette.bull
            : palette.bear
          : `rgba(${bull ? palette.rgb.bull : palette.rgb.bear},0.25)`,
        text: label,
      } as SeriesMarker<Time>;
    });
}

function chartColors(p: ChartPalette) {
  return {
    layout: {
      background: { type: ColorType.Solid, color: p.background },
      textColor: p.text,
      fontFamily: getComputedStyle(document.body).fontFamily,
      // D-ATTR: the library's TradingView logo (links to tradingview.com) is the attribution.
      attributionLogo: true,
    },
    grid: { vertLines: { color: p.grid }, horzLines: { color: p.grid } },
    rightPriceScale: { borderColor: p.grid },
    timeScale: { borderColor: p.grid },
  };
}

function seriesOptions(style: ChartStyle, p: ChartPalette) {
  switch (style) {
    case "hollow":
      return {
        upColor: "rgba(0,0,0,0)",
        downColor: p.bear,
        borderVisible: true,
        borderUpColor: p.bull,
        borderDownColor: p.bear,
        wickUpColor: p.bull,
        wickDownColor: p.bear,
      };
    case "bars":
      return { upColor: p.bull, downColor: p.bear, thinBars: false };
    case "line":
      return { color: p.primary, lineWidth: 2 as const };
    case "area":
      return {
        lineColor: p.primary,
        lineWidth: 2 as const,
        topColor: `rgba(${p.rgb.primary},0.28)`,
        bottomColor: `rgba(${p.rgb.primary},0.02)`,
      };
    default:
      return {
        upColor: p.bull,
        downColor: p.bear,
        wickUpColor: p.bull,
        wickDownColor: p.bear,
        borderVisible: false,
      };
  }
}

function addSeries(chart: IChartApi, style: ChartStyle, p: ChartPalette): ISeriesApi<SeriesType> {
  const opts = seriesOptions(style, p);
  if (style === "bars") return chart.addSeries(BarSeries, opts);
  if (style === "line") return chart.addSeries(LineSeries, opts);
  if (style === "area") return chart.addSeries(AreaSeries, opts);
  return chart.addSeries(CandlestickSeries, opts);
}

type Drag = { id: string; handle: number | null; start: Point; orig: Drawing; moved: boolean };
type Draft = { kind: DrawingKind | "measure"; a: Point; b: Point; downX: number; downY: number };

// Candles with SMC overlays and the user's drawings (FR-CHART-01..05). Colours come from the
// theme tokens and follow theme changes; the series type follows the chart style.
export function Chart(props: Props) {
  const { payload, layers, highlightZone, timeZone, livePrice, style } = props;
  const stage = useRef<HTMLDivElement | null>(null);
  const box = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<SeriesType> | null>(null);
  const overlayRef = useRef<OverlayPrimitive | null>(null);
  const drawRef = useRef<DrawingLayer | null>(null);
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const priceLine = useRef<IPriceLine | null>(null);
  const [palette, setPalette] = useState<ChartPalette | null>(null);
  const [version, setVersion] = useState(0);
  const [flash, setFlash] = useState<string | null>(null);
  const draft = useRef<Draft | null>(null);
  const drag = useRef<Drag | null>(null);
  const [measureState, setMeasureState] = useState<MeasureState>(null);
  const [note, setNote] = useState<{ x: number; y: number; at: Point } | null>(null);
  const latest = useRef(props);
  latest.current = props;

  useEffect(() => {
    setPalette(readChartPalette());
    return onThemeChange(() => setPalette(readChartPalette()));
  }, []);

  useEffect(() => {
    if (!box.current) return;
    const p = readChartPalette();
    const chart = createChart(box.current, {
      autoSize: true,
      ...chartColors(p),
      timeScale: { timeVisible: true, secondsVisible: false, borderColor: p.grid, rightOffset: 6 },
      localization: { timeFormatter: (t: Time) => axisLabel(Number(t), timeZone, false) },
    });
    const series = addSeries(chart, style, p);
    const overlay = new OverlayPrimitive();
    overlay.setPalette(p);
    series.attachPrimitive(overlay);
    const layer = new DrawingLayer();
    layer.setPalette(p);
    series.attachPrimitive(layer);
    chartRef.current = chart;
    seriesRef.current = series;
    overlayRef.current = overlay;
    drawRef.current = layer;
    markersRef.current = createSeriesMarkers(series, []);
    setVersion((v) => v + 1);
    return () => {
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
      overlayRef.current = null;
      drawRef.current = null;
      markersRef.current = null;
      priceLine.current = null;
    };
  }, [timeZone, style]);

  // Theme change: recolour in place.
  useEffect(() => {
    if (!palette) return;
    chartRef.current?.applyOptions(chartColors(palette));
    seriesRef.current?.applyOptions(seriesOptions(style, palette));
    overlayRef.current?.setPalette(palette);
    drawRef.current?.setPalette(palette);
  }, [palette, style, version]);

  useEffect(() => {
    const chart = chartRef.current;
    const series = seriesRef.current;
    if (!chart || !series || !palette) return;
    const scale = 10 ** payload.price_scale;
    chart.applyOptions({
      timeScale: {
        tickMarkFormatter: (t: Time, type: number) => axisLabel(Number(t), timeZone, type <= 2),
      },
    });
    series.applyOptions({
      priceFormat: { type: "price", precision: payload.price_scale, minMove: 1 / scale },
    });
    const bars = payload.candles.map((c) => ({
      time: toUnixSeconds(c.t) as UTCTimestamp,
      open: c.o / scale,
      high: c.h / scale,
      low: c.l / scale,
      close: c.c / scale,
    }));
    series.setData(seriesData(bars, style) as Parameters<typeof series.setData>[0]);
    markersRef.current?.setMarkers(
      layers.structure ? markers(payload, palette, props.patternFilter ?? null) : [],
    );
    overlayRef.current?.set(payload, layers, flash ?? highlightZone);
    drawRef.current?.setData(
      bars.map((b) => b.time as number),
      TF_SECONDS[payload.timeframe] ?? 3600,
      payload.price_scale,
    );
    box.current?.setAttribute("data-painted", "true");
    if (highlightZone && payload.zones.some((z) => z.id === highlightZone)) {
      box.current?.setAttribute("data-highlighted-zone", highlightZone);
    } else {
      box.current?.removeAttribute("data-highlighted-zone");
    }
  }, [
    payload,
    layers,
    highlightZone,
    timeZone,
    palette,
    style,
    version,
    flash,
    props.patternFilter,
  ]);

  useEffect(() => {
    overlayRef.current?.setExtras(props.patternFilter ?? null, props.candidates ?? []);
    box.current?.toggleAttribute("data-filtered", Boolean(props.patternFilter));
    box.current?.setAttribute("data-candidates", String(props.candidates?.length ?? 0));
  }, [props.patternFilter, props.candidates, version]);

  // Focus from the analysis list: scroll the time into view and flash its zone.
  useEffect(() => {
    const f = props.focus;
    const chart = chartRef.current;
    if (!f || !chart || payload.candles.length === 0) return;
    const t = toUnixSeconds(f.time);
    let i = payload.candles.findIndex((c) => toUnixSeconds(c.t) >= t);
    if (i < 0) i = payload.candles.length - 1;
    chart.timeScale().setVisibleLogicalRange({ from: i - 60, to: i + 20 });
    box.current?.setAttribute("data-focused", f.time);
    if (!f.zoneId) return;
    setFlash(f.zoneId);
    const timer = setTimeout(() => setFlash(null), 1600);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.focus?.nonce, version]);

  // Forming candle: appended after the data effect, updated in place on every price tick.
  const { forming } = props;
  const [formingRight, setFormingRight] = useState<number | null>(null);
  useEffect(() => {
    const chart = chartRef.current;
    const series = seriesRef.current;
    if (!chart || !series || !palette) return;
    if (!forming) {
      setFormingRight(null);
      box.current?.removeAttribute("data-forming");
      return;
    }
    const scale = 10 ** payload.price_scale;
    const bars = payload.candles.map((c) => ({
      time: toUnixSeconds(c.t) as UTCTimestamp,
      open: c.o / scale,
      high: c.h / scale,
      low: c.l / scale,
      close: c.c / scale,
    }));
    const time = toUnixSeconds(forming.t) as UTCTimestamp;
    if (bars.length && time <= bars[bars.length - 1].time) return;
    const bar = {
      time,
      open: forming.o / scale,
      high: forming.h / scale,
      low: forming.l / scale,
      close: forming.c / scale,
    };
    const all = seriesData([...bars, bar], style);
    const last = all[all.length - 1] as Record<string, number>;
    const up = "open" in last ? last.close >= last.open : true;
    const fade = (rgb: string) => `rgba(${rgb},0.45)`;
    const tone = fade(up ? palette.rgb.bull : palette.rgb.bear);
    let point: Record<string, unknown>;
    if (style === "line") point = { ...last, color: fade(palette.rgb.primary) };
    else if (style === "area")
      point = {
        ...last,
        lineColor: fade(palette.rgb.primary),
        topColor: `rgba(${palette.rgb.primary},0.12)`,
      };
    else if (style === "bars") point = { ...last, color: tone };
    else if (style === "hollow")
      point = { ...last, color: up ? "rgba(0,0,0,0)" : tone, borderColor: tone, wickColor: tone };
    else point = { ...last, color: tone, borderColor: tone, wickColor: tone };
    series.update(point as unknown as Parameters<typeof series.update>[0]);
    box.current?.setAttribute("data-forming", "true");
    setFormingRight(chart.priceScale("right").width() + 8);
  }, [forming, payload, style, palette, version]);

  useEffect(() => {
    drawRef.current?.setState({
      drawings: props.drawings,
      selectedId: props.selectedId,
      hidden: props.hidden,
    });
  }, [props.drawings, props.selectedId, props.hidden, version]);

  useEffect(() => {
    drawRef.current?.setState({ measure: measureState });
  }, [measureState, version]);

  // Esc: cancel whatever is in progress.
  useEffect(() => {
    draft.current = null;
    drag.current = null;
    drawRef.current?.setState({ draft: null });
    setMeasureState(null);
    setNote(null);
  }, [props.cancelNonce]);

  // Drawing tools take the pointer: the chart stops panning while one is active.
  useEffect(() => {
    const drawing = props.tool !== "select";
    chartRef.current?.applyOptions({ handleScroll: !drawing, handleScale: !drawing });
  }, [props.tool, version]);

  useEffect(() => {
    const series = seriesRef.current;
    if (!series) return;
    if (priceLine.current) series.removePriceLine(priceLine.current);
    priceLine.current =
      livePrice === null
        ? null
        : series.createPriceLine({
            price: livePrice / 10 ** payload.price_scale,
            color: palette?.primary ?? "#7cb0ff",
            lineStyle: LineStyle.Dotted,
            lineWidth: 1,
            title: "live",
          });
  }, [livePrice, payload.price_scale, palette, version]);

  // ---------------------------------------------------------------- pointer handling
  function local(e: ReactPointerEvent) {
    const r = box.current!.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  }

  /** Chart point under the pointer; trend, ray and fib points snap to OHLC within 6 px. */
  function pointAt(x: number, y: number, kind: Tool, noSnap: boolean): Point | null {
    const layer = drawRef.current;
    if (!layer) return null;
    const pt = layer.unproject(x, y);
    if (!pt || noSnap || !(kind === "trend" || kind === "ray" || kind === "fib")) return pt;
    const i = layer.barIndexAt(x);
    if (i === null) return pt;
    const c = latest.current.payload.candles[i];
    let best: Point | null = null;
    let bestD = SNAP_PX;
    for (const p of [c.o, c.h, c.l, c.c]) {
      const py = layer.priceToY(p);
      if (py !== null && Math.abs(py - y) <= bestD) {
        bestD = Math.abs(py - y);
        best = { t: layer.barTime(i), p };
      }
    }
    return best ?? pt;
  }

  function finishDraft(d: Draft) {
    draft.current = null;
    drawRef.current?.setState({ draft: null });
    if (d.kind === "measure") {
      setMeasureState({ a: d.a, b: d.b });
    } else {
      latest.current.onDraw(createDrawing(d.kind, [d.a, d.b]));
    }
    latest.current.onToolDone();
  }

  function onPointerDownCapture(e: ReactPointerEvent<HTMLDivElement>) {
    if (e.button !== 0 || !drawRef.current) return;
    const { x, y } = local(e);
    if (x > drawRef.current.paneWidth()) return; // price axis
    const { tool, drawings, locked, hidden } = latest.current;
    if (measureState) setMeasureState(null);
    if (note) return;

    if (tool === "select") {
      if (hidden) return;
      const layer = drawRef.current;
      for (let i = drawings.length - 1; i >= 0; i--) {
        const h = hitTest(drawings[i], layer.project, x, y, layer.paneWidth());
        if (!h.hit) continue;
        latest.current.onSelect(drawings[i].id);
        if (locked) return;
        const start = layer.unproject(x, y);
        if (!start) return;
        drag.current = {
          id: drawings[i].id,
          handle: h.handle,
          start,
          orig: drawings[i],
          moved: false,
        };
        e.preventDefault();
        e.stopPropagation();
        stage.current?.setPointerCapture(e.pointerId);
        chartRef.current?.applyOptions({ handleScroll: false, handleScale: false });
        return;
      }
      if (latest.current.selectedId) latest.current.onSelect(null);
      return;
    }

    e.preventDefault();
    e.stopPropagation();
    const pt = pointAt(x, y, tool, e.altKey);
    if (!pt) return;
    if (tool === "text") {
      setNote({ x, y, at: pt });
      return;
    }
    if (tool === "hline") {
      latest.current.onDraw(createDrawing("hline", [pt]));
      latest.current.onToolDone();
      return;
    }
    const current = draft.current;
    if (current) {
      finishDraft({ ...current, b: pt });
      return;
    }
    draft.current = { kind: tool, a: pt, b: pt, downX: x, downY: y };
    if (tool !== "measure" && POINTS_NEEDED[tool] === 2) {
      drawRef.current.setState({ draft: createDrawing(tool, [pt, pt], { id: "draft" }) });
    }
    stage.current?.setPointerCapture(e.pointerId);
  }

  function onPointerMove(e: ReactPointerEvent<HTMLDivElement>) {
    const layer = drawRef.current;
    if (!layer) return;
    const { x, y } = local(e);
    const d = drag.current;
    if (d) {
      const cur = layer.unproject(x, y);
      if (!cur) return;
      d.moved = true;
      const next =
        d.handle === null
          ? moveDrawing(d.orig, cur.t - d.start.t, cur.p - d.start.p)
          : moveHandle(d.orig, d.handle, cur);
      layer.setState({
        drawings: latest.current.drawings.map((x2) => (x2.id === d.id ? next : x2)),
      });
      return;
    }
    const dr = draft.current;
    if (dr) {
      const pt = pointAt(x, y, dr.kind, e.altKey);
      if (!pt) return;
      dr.b = pt;
      if (dr.kind === "measure") setMeasureState({ a: dr.a, b: pt });
      else layer.setState({ draft: createDrawing(dr.kind, [dr.a, pt], { id: "draft" }) });
      return;
    }
    // Hover feedback in select mode.
    const { tool, drawings, hidden, locked } = latest.current;
    if (!stage.current) return;
    if (tool !== "select") {
      stage.current.style.cursor = "crosshair";
      return;
    }
    let cursor = "";
    if (!hidden && x <= layer.paneWidth()) {
      for (let i = drawings.length - 1; i >= 0; i--) {
        const h = hitTest(drawings[i], layer.project, x, y, layer.paneWidth());
        if (h.hit) {
          cursor = locked ? "pointer" : h.handle !== null ? "grab" : "move";
          break;
        }
      }
    }
    stage.current.style.cursor = cursor;
  }

  function onPointerUp(e: ReactPointerEvent<HTMLDivElement>) {
    const d = drag.current;
    if (d) {
      drag.current = null;
      chartRef.current?.applyOptions({
        handleScroll: latest.current.tool === "select",
        handleScale: latest.current.tool === "select",
      });
      if (!d.moved) return;
      const layer = drawRef.current;
      const { x, y } = local(e);
      const cur = layer?.unproject(x, y);
      if (!cur) return;
      latest.current.onChangeDrawing(
        d.handle === null
          ? moveDrawing(d.orig, cur.t - d.start.t, cur.p - d.start.p)
          : moveHandle(d.orig, d.handle, cur),
      );
      return;
    }
    const dr = draft.current;
    if (dr) {
      const { x, y } = local(e);
      // Drag-to-draw: release finishes; a plain click waits for the second click.
      if (Math.hypot(x - dr.downX, y - dr.downY) > 4) finishDraft(dr);
    }
  }

  function saveNote(text: string) {
    const n = note;
    setNote(null);
    const value = text.trim().slice(0, 140);
    if (n && value) props.onDraw(createDrawing("text", [n.at], { text: value }));
    props.onToolDone();
  }

  return (
    <div
      ref={stage}
      className="chart-stage"
      data-tool={props.tool}
      onPointerDownCapture={onPointerDownCapture}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
    >
      <div
        ref={box}
        className="chart-canvas"
        data-testid="chart"
        data-style={style}
        data-drawings={props.drawings.length}
      />
      {forming && formingRight !== null && (
        <span
          className="forming-label"
          style={{ right: formingRight }}
          title="Forming candle: not final, never used for setups"
          data-testid="forming-label"
        >
          Forming · not final
        </span>
      )}
      {note && (
        <input
          className="chart-note-input"
          style={{ left: note.x, top: Math.max(0, note.y - 34) }}
          aria-label="Note text"
          placeholder="Type a note, then press Enter"
          maxLength={140}
          autoFocus
          onKeyDown={(e) => {
            if (e.key === "Enter") saveNote(e.currentTarget.value);
            if (e.key === "Escape") {
              e.stopPropagation();
              setNote(null);
              props.onToolDone();
            }
          }}
          onBlur={(e) => saveNote(e.currentTarget.value)}
        />
      )}
    </div>
  );
}
