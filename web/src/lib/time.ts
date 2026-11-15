// Times are stored in UTC and shown in the user's timezone (FR-ACC-04, Detailed Design 5.2).

export function formatTime(iso: string | null | undefined, timeZone: string): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat("en-GB", {
    timeZone,
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(new Date(iso));
}

export function toUnixSeconds(iso: string): number {
  return Math.floor(Date.parse(iso) / 1000);
}

/** Label for chart axes: the wall time of a UTC timestamp in `timeZone`. */
export function axisLabel(unixSeconds: number, timeZone: string, withDate: boolean): string {
  return new Intl.DateTimeFormat("en-GB", {
    timeZone,
    ...(withDate ? { day: "2-digit", month: "short" } : { hour: "2-digit", minute: "2-digit" }),
    hourCycle: "h23",
  }).format(new Date(unixSeconds * 1000));
}

export const TIMEFRAME_LABELS: Record<string, string> = {
  "5m": "5m",
  "15m": "15m",
  "1h": "1H",
  "4h": "4H",
  "1d": "1D (NY close)",
};
