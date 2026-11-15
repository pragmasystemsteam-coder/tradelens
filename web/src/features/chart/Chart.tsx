"use client";

import {
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  LineStyle,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef } from "react";

import { axisLabel, toUnixSeconds } from "@/lib/time";
import type { ChartPayload } from "@/lib/types";

import { type Layers, OverlayPrimitive, snap } from "./Overlays";

type Props = {
  payload: ChartPayload;
  layers: Layers;
  highlightZone: string | null;
  timeZone: string;
  livePrice: number | null;
};

const MARKED = new Set(["bos", "choch", "sweep"]);

function markers(payload: ChartPayload): SeriesMarker<Time>[] {
  const bars = payload.candles.map((c) => toUnixSeconds(c.t));
  const tfSeconds = bars.length > 1 ? bars[1] - bars[0] : 3600;
  return payload.events
    .filter((e) => MARKED.has(e.type))
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
        color: bull ? "#26a69a" : "#ef5350",
        text: label,
      } as SeriesMarker<Time>;
    });
}

// Candles with overlays as a Lightweight Charts series and primitive (FR-CHART-01..05).
export function Chart({ payload, layers, highlightZone, timeZone, livePrice }: Props) {
  const box = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const overlayRef = useRef<OverlayPrimitive | null>(null);
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const priceLine = useRef<IPriceLine | null>(null);

  useEffect(() => {
    if (!box.current) return;
    const chart = createChart(box.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "#ffffff" }, textColor: "#333" },
      grid: { vertLines: { color: "#f0f0f0" }, horzLines: { color: "#f0f0f0" } },
      timeScale: { timeVisible: true, secondsVisible: false },
      localization: { timeFormatter: (t: Time) => axisLabel(Number(t), timeZone, false) },
    });
    const series = chart.addSeries(CandlestickSeries, {
      upColor: "#26a69a",
      downColor: "#ef5350",
      wickUpColor: "#26a69a",
      wickDownColor: "#ef5350",
      borderVisible: false,
    });
    const overlay = new OverlayPrimitive();
    series.attachPrimitive(overlay);
    chartRef.current = chart;
    seriesRef.current = series;
    overlayRef.current = overlay;
    markersRef.current = createSeriesMarkers(series, []);
    return () => {
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
      overlayRef.current = null;
      markersRef.current = null;
      priceLine.current = null;
    };
  }, [timeZone]);

  useEffect(() => {
    const chart = chartRef.current;
    const series = seriesRef.current;
    if (!chart || !series) return;
    const scale = 10 ** payload.price_scale;
    chart.applyOptions({
      timeScale: {
        tickMarkFormatter: (t: Time, type: number) => axisLabel(Number(t), timeZone, type <= 2),
      },
    });
    series.applyOptions({
      priceFormat: { type: "price", precision: payload.price_scale, minMove: 1 / scale },
    });
    series.setData(
      payload.candles.map((c) => ({
        time: toUnixSeconds(c.t) as UTCTimestamp,
        open: c.o / scale,
        high: c.h / scale,
        low: c.l / scale,
        close: c.c / scale,
      })),
    );
    markersRef.current?.setMarkers(layers.structure ? markers(payload) : []);
    overlayRef.current?.set(payload, layers, highlightZone);
    box.current?.setAttribute("data-painted", "true");
    if (highlightZone && payload.zones.some((z) => z.id === highlightZone)) {
      box.current?.setAttribute("data-highlighted-zone", highlightZone);
    } else {
      box.current?.removeAttribute("data-highlighted-zone");
    }
  }, [payload, layers, highlightZone, timeZone]);

  useEffect(() => {
    const series = seriesRef.current;
    if (!series) return;
    if (priceLine.current) series.removePriceLine(priceLine.current);
    priceLine.current =
      livePrice === null
        ? null
        : series.createPriceLine({
            price: livePrice / 10 ** payload.price_scale,
            color: "#2962ff",
            lineStyle: LineStyle.Dotted,
            lineWidth: 1,
            title: "live",
          });
  }, [livePrice, payload.price_scale]);

  return <div ref={box} className="chart-canvas" data-testid="chart" />;
}
