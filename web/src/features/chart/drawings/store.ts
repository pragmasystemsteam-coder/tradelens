// Where drawings are kept. Today: this browser (localStorage), per user, instrument and
// timeframe. The interface lets a server table replace it later without touching the chart.

import { deserialize, emptyChart, type SavedChart, serialize } from "./model";

export interface DrawingStore {
  load(key: string): SavedChart;
  save(key: string, chart: SavedChart): void;
  clear(key: string): void;
}

export function drawingKey(userId: string, instrument: string, timeframe: string): string {
  return `tl:drawings:v1:${userId}:${instrument}:${timeframe}`;
}

export const localDrawingStore: DrawingStore = {
  load(key) {
    try {
      return deserialize(window.localStorage.getItem(key));
    } catch {
      return emptyChart();
    }
  },
  save(key, chart) {
    try {
      if (chart.drawings.length === 0 && !chart.locked && !chart.hidden)
        window.localStorage.removeItem(key);
      else window.localStorage.setItem(key, serialize(chart));
    } catch {
      // Storage full or blocked: drawings last for this visit only.
    }
  },
  clear(key) {
    try {
      window.localStorage.removeItem(key);
    } catch {
      // Nothing to clear.
    }
  },
};
