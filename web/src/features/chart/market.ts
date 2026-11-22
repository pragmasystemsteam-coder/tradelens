// FX market clock: the trading day starts at 17:00 New York (like our 1D candle), the market
// is closed from Friday 17:00 to Sunday 17:00 New York. Pure functions, unit-tested in
// market.test.ts.

const NY = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York",
  hourCycle: "h23",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  weekday: "short",
});

type NyParts = { y: number; mo: number; d: number; h: number; mi: number; s: number; wd: string };

function nyParts(ms: number): NyParts {
  const p: Record<string, string> = {};
  for (const part of NY.formatToParts(new Date(ms))) p[part.type] = part.value;
  return {
    y: +p.year,
    mo: +p.month,
    d: +p.day,
    h: +p.hour,
    mi: +p.minute,
    s: +p.second,
    wd: p.weekday,
  };
}

/** New York's offset from UTC at this moment, in ms (negative: behind UTC). */
function nyOffset(ms: number): number {
  const p = nyParts(ms);
  const wall = Date.UTC(p.y, p.mo - 1, p.d, p.h, p.mi, p.s);
  return wall - Math.floor(ms / 1000) * 1000;
}

/** The most recent 17:00 New York at or before `ms`. */
export function tradingDayStart(ms: number): number {
  const p = nyParts(ms);
  let day = Date.UTC(p.y, p.mo - 1, p.d, 17, 0, 0);
  if (p.h < 17) day -= 86_400_000;
  // `day` is 17:00 as New York wall time written in UTC; shift by that day's offset.
  return day - nyOffset(day - nyOffset(ms));
}

export function isMarketClosed(ms: number): boolean {
  const { wd, h } = nyParts(ms);
  if (wd === "Sat") return true;
  if (wd === "Fri") return h >= 17;
  if (wd === "Sun") return h < 17;
  return false;
}

/** When the market next opens (Sunday 17:00 New York), for the closed-market label. */
export function nextOpenMs(ms: number): number {
  let t = tradingDayStart(ms) + 86_400_000;
  while (isMarketClosed(t + 60_000)) t += 86_400_000;
  return t;
}

/** Close time of the forming candle: the one after the last complete candle. */
export function nextCloseMs(lastOpenSec: number, tfSec: number, nowMs: number): number {
  const step = tfSec * 1000;
  let close = lastOpenSec * 1000 + 2 * step;
  if (close <= nowMs) close += Math.ceil((nowMs - close + 1) / step) * step;
  return close;
}

export function formatCountdown(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  const pad = (n: number) => String(n).padStart(2, "0");
  if (s < 3600) return `${pad(Math.floor(s / 60))}:${pad(s % 60)}`;
  if (s < 86_400) return `${Math.floor(s / 3600)}h ${pad(Math.floor((s % 3600) / 60))}m`;
  return `${Math.floor(s / 86_400)}d ${Math.floor((s % 86_400) / 3600)}h`;
}

/** Change of `last` against the open of the current trading day, in price units and percent. */
export function dayChange(
  candles: { t: string; o: number }[],
  last: number | null,
  nowMs: number,
): { units: number; percent: number } | null {
  if (last === null) return null;
  const start = tradingDayStart(nowMs);
  const first = candles.find((c) => Date.parse(c.t) >= start);
  if (!first || first.o === 0) return null;
  const units = last - first.o;
  return { units, percent: (units / first.o) * 100 };
}
