// Drawing model for the chart workspace: shapes, hit-testing, history and saving.
// Plain TypeScript with no chart dependency, so it is unit-tested on its own
// (model.test.ts). Points are stored as candle time (unix seconds) plus integer price units,
// so drawings stay in place when the chart zooms or new candles arrive.

export type Point = { t: number; p: number };
export type DrawingKind = "trend" | "hline" | "ray" | "rect" | "fib" | "text";
export type Tone = "neutral" | "bull" | "bear";
export type Drawing = {
  id: string;
  kind: DrawingKind;
  points: Point[];
  text?: string;
  tone?: Tone;
};
export type SavedChart = { v: 1; drawings: Drawing[]; locked: boolean; hidden: boolean };

/** Maps a chart point to pane pixels, or null when it cannot be placed. */
export type Projector = (pt: Point) => { x: number; y: number } | null;

export const KINDS: DrawingKind[] = ["trend", "hline", "ray", "rect", "fib", "text"];
export const POINTS_NEEDED: Record<DrawingKind, number> = {
  trend: 2,
  hline: 1,
  ray: 2,
  rect: 2,
  fib: 2,
  text: 1,
};
export const FIB_LEVELS = [0, 0.236, 0.382, 0.5, 0.618, 0.705, 0.786, 1];
export const MAX_HISTORY = 50;
export const TOLERANCE = 6;

let counter = 0;
function newId(): string {
  counter += 1;
  return `d${Date.now().toString(36)}${counter.toString(36)}${Math.random().toString(36).slice(2, 6)}`;
}

export function createDrawing(
  kind: DrawingKind,
  points: Point[],
  extra: { text?: string; tone?: Tone; id?: string } = {},
): Drawing {
  if (points.length !== POINTS_NEEDED[kind]) {
    throw new Error(`${kind} needs ${POINTS_NEEDED[kind]} point(s), got ${points.length}`);
  }
  const d: Drawing = {
    id: extra.id ?? newId(),
    kind,
    points: points.map((pt) => ({ t: pt.t, p: Math.round(pt.p) })),
  };
  if (extra.text !== undefined) d.text = extra.text;
  if (extra.tone !== undefined) d.tone = extra.tone;
  return d;
}

export function moveDrawing(d: Drawing, dt: number, dp: number): Drawing {
  return { ...d, points: d.points.map((pt) => ({ t: pt.t + dt, p: Math.round(pt.p + dp) })) };
}

export function moveHandle(d: Drawing, index: number, to: Point): Drawing {
  return {
    ...d,
    points: d.points.map((pt, i) => (i === index ? { t: to.t, p: Math.round(to.p) } : pt)),
  };
}

function distToSegment(px: number, py: number, ax: number, ay: number, bx: number, by: number) {
  const dx = bx - ax;
  const dy = by - ay;
  const len2 = dx * dx + dy * dy;
  const u = len2 === 0 ? 0 : Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / len2));
  return Math.hypot(px - (ax + u * dx), py - (ay + u * dy));
}

function distToRay(px: number, py: number, ax: number, ay: number, bx: number, by: number) {
  const dx = bx - ax;
  const dy = by - ay;
  const len2 = dx * dx + dy * dy;
  const u = len2 === 0 ? 0 : Math.max(0, ((px - ax) * dx + (py - ay) * dy) / len2);
  return Math.hypot(px - (ax + u * dx), py - (ay + u * dy));
}

/** Approximate label box of a text note, anchored at its point (bottom-left). */
export function textBox(text: string | undefined) {
  return { w: Math.max(24, (text ?? "").length * 6.5 + 14), h: 20 };
}

export function fibLevels(d: Drawing): { level: number; p: number }[] {
  const [a, b] = d.points;
  return FIB_LEVELS.map((level) => ({ level, p: Math.round(b.p - (b.p - a.p) * level) }));
}

export function hitTest(
  d: Drawing,
  project: Projector,
  x: number,
  y: number,
  paneWidth: number,
  tol = TOLERANCE,
): { hit: boolean; handle: number | null } {
  const pts = d.points.map(project);
  if (pts.some((p) => p === null)) return { hit: false, handle: null };
  const xy = pts as { x: number; y: number }[];
  if (d.kind !== "hline" && d.kind !== "text") {
    const handle = xy.findIndex((p) => Math.hypot(p.x - x, p.y - y) <= tol + 2);
    if (handle >= 0) return { hit: true, handle };
  }
  let hit = false;
  switch (d.kind) {
    case "trend":
      hit = distToSegment(x, y, xy[0].x, xy[0].y, xy[1].x, xy[1].y) <= tol;
      break;
    case "ray":
      hit = distToRay(x, y, xy[0].x, xy[0].y, xy[1].x, xy[1].y) <= tol;
      break;
    case "hline":
      hit = x >= 0 && x <= paneWidth && Math.abs(y - xy[0].y) <= tol;
      break;
    case "rect": {
      const [l, r] = [Math.min(xy[0].x, xy[1].x), Math.max(xy[0].x, xy[1].x)];
      const [t, b] = [Math.min(xy[0].y, xy[1].y), Math.max(xy[0].y, xy[1].y)];
      hit = x >= l - tol && x <= r + tol && y >= t - tol && y <= b + tol;
      break;
    }
    case "fib": {
      const left = Math.min(xy[0].x, xy[1].x);
      if (x < left - tol || x > paneWidth) break;
      hit = fibLevels(d).some((lv) => {
        const p = project({ t: d.points[0].t, p: lv.p });
        return p !== null && Math.abs(p.y - y) <= tol;
      });
      break;
    }
    case "text": {
      const box = textBox(d.text);
      hit = x >= xy[0].x - 2 && x <= xy[0].x + box.w && y >= xy[0].y - box.h && y <= xy[0].y + 2;
      break;
    }
  }
  return { hit, handle: null };
}

export function measure(a: Point, b: Point, tfSeconds: number, priceScale: number) {
  const units = Math.round(b.p - a.p);
  const pipUnits = priceScale >= 3 ? 10 : 1;
  return {
    units,
    pips: units / pipUnits,
    percent: a.p === 0 ? 0 : (units / a.p) * 100,
    bars: tfSeconds > 0 ? Math.round((b.t - a.t) / tfSeconds) : 0,
  };
}

export type History = { past: Drawing[][]; present: Drawing[]; future: Drawing[][] };

export function historyInit(present: Drawing[]): History {
  return { past: [], present, future: [] };
}

export function commit(h: History, next: Drawing[]): History {
  return { past: [...h.past, h.present].slice(-MAX_HISTORY), present: next, future: [] };
}

export function undo(h: History): History {
  if (h.past.length === 0) return h;
  return {
    past: h.past.slice(0, -1),
    present: h.past[h.past.length - 1],
    future: [h.present, ...h.future],
  };
}

export function redo(h: History): History {
  if (h.future.length === 0) return h;
  return { past: [...h.past, h.present], present: h.future[0], future: h.future.slice(1) };
}

export function emptyChart(): SavedChart {
  return { v: 1, drawings: [], locked: false, hidden: false };
}

export function serialize(s: SavedChart): string {
  return JSON.stringify(s);
}

function validPoint(p: unknown): p is Point {
  const q = p as Point;
  return !!q && Number.isFinite(q.t) && Number.isFinite(q.p);
}

function validDrawing(d: unknown): d is Drawing {
  const q = d as Drawing;
  return (
    !!q &&
    typeof q.id === "string" &&
    KINDS.includes(q.kind) &&
    Array.isArray(q.points) &&
    q.points.length === POINTS_NEEDED[q.kind] &&
    q.points.every(validPoint) &&
    (q.text === undefined || typeof q.text === "string")
  );
}

/** Reads saved drawings; anything missing, broken or unknown becomes an empty chart. */
export function deserialize(raw: string | null): SavedChart {
  if (!raw) return emptyChart();
  try {
    const doc = JSON.parse(raw) as Partial<SavedChart>;
    if (doc.v !== 1 || !Array.isArray(doc.drawings)) return emptyChart();
    return {
      v: 1,
      drawings: doc.drawings.filter(validDrawing),
      locked: doc.locked === true,
      hidden: doc.hidden === true,
    };
  } catch {
    return emptyChart();
  }
}
