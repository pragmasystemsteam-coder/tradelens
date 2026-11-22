// IANA time zones for the sign-up and profile pickers (FR-ACC-04). The browser's own zone is
// the default; the list comes from Intl where the browser supports it.

type IntlWithZones = typeof Intl & { supportedValuesOf?: (key: "timeZone") => string[] };

export function detectedTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

export function timeZones(include: string[] = []): string[] {
  let zones: string[] = [];
  try {
    zones = (Intl as IntlWithZones).supportedValuesOf?.("timeZone") ?? [];
  } catch {
    zones = [];
  }
  return Array.from(new Set([...include, "UTC", ...zones])).sort((a, b) => a.localeCompare(b));
}

export const TRADING_STYLES = [
  { value: "scalping", label: "Scalping" },
  { value: "intraday", label: "Intraday" },
  { value: "swing", label: "Swing" },
] as const;

export type TradingStyle = (typeof TRADING_STYLES)[number]["value"];
