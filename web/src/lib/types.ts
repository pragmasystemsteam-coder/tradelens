// Response shapes of the customer API (Detailed Design 4.2). Prices are integers in the
// instrument's smallest unit with `price_scale` beside them; times are ISO 8601 UTC.

export type Direction = "bull" | "bear";
export type SetupTimeframe = "15m" | "1h" | "4h";
export type ChartTimeframe = "5m" | "15m" | "1h" | "4h" | "1d";

export interface Entitlements {
  asset_classes: string[];
  mtf_detail: "strip" | "full";
  chart_history_candles: number;
  max_watchlists: number | null;
  max_watchlist_items: number | null;
  custom_settings: boolean;
  [key: string]: unknown;
}

export interface Me {
  user: {
    id: string;
    email: string;
    name: string;
    timezone: string;
    trading_style: "scalping" | "intraday" | "swing";
    billing_country: string | null;
  };
  plan: { code: string; name: string };
  entitlements: Entitlements;
  subscription: { status: string; trial_ends_at: string | null } | null;
}

export interface SetupRow {
  id: string;
  instrument: string;
  display_name: string;
  asset_class: string;
  price_scale: number;
  timeframe: SetupTimeframe;
  profile: string;
  direction: Direction;
  patterns: string[];
  sessions: string[];
  q: number;
  c: number;
  combined: number;
  high_quality: boolean;
  counter_trend: boolean;
  zone: { low: number; high: number };
  zone_state: string;
  invalidation: number;
  spread: number;
  status: string;
  confirm_time: string;
}

export interface SetupsPage {
  items: SetupRow[];
  next_cursor: string | null;
  data_as_of: string | null;
  series_delayed: string[];
}

export interface Factor {
  code: string;
  score: "Q" | "C";
  points: number | null;
  max: number;
  reason: string | null;
  locked: boolean;
}

export interface SetupDetail extends SetupRow {
  factors: Factor[];
  explanation: string;
  opposing_level: number | null;
  origin_time: string;
  rule_version: string;
  scoring_version: string;
  mtf: { timeframe: string; role: string; trend_internal: string | null }[];
  revisions: { at: string; combined: number; status: string; reason: string }[];
}

export interface Candle {
  t: string;
  o: number;
  h: number;
  l: number;
  c: number;
  spread: number;
}

export interface ChartEvent {
  id: string;
  type: string;
  structure: string | null;
  direction: Direction | null;
  level: number | null;
  origin_time: string;
  confirm_time: string;
}

export interface ChartZone {
  id: string;
  kind: "ob" | "fvg";
  direction: Direction;
  low: number;
  high: number;
  state: string;
  state_time?: string;
  origin_time: string;
  confirm_time: string;
}

export interface LiquidityLevel {
  id: string;
  kinds: string[];
  side: "buy" | "sell";
  price: number;
  origin_time: string;
  confirm_time: string;
  status: "active" | "ended";
  end_reason: string | null;
  end_time: string | null;
}

export interface ChartPayload {
  instrument: string;
  timeframe: ChartTimeframe;
  price_scale: number;
  settings: { kind: string; preset: string; rule_version: string };
  status: { state: string; delayed_since: string | null; last_candle_time: string | null };
  candles: Candle[];
  has_more: boolean;
  events: ChartEvent[];
  zones: ChartZone[];
  htf_zones: (ChartZone & { timeframe: string })[];
  liquidity: LiquidityLevel[];
  setups: { id: string; direction: Direction; combined: number; status: string; zone_id: string }[];
  trend_strip: { timeframe: string; internal: string; external: string; as_of: string | null }[];
  provisional: {
    swings: { type: string; structure: string; price: number; origin_time: string }[];
  };
  live_price: { bid: number; ask: number; mid: number; time: string; stale: boolean } | null;
}

export interface Instrument {
  code: string;
  display_name: string;
  asset_class: string;
  price_scale: number;
  available: boolean;
}

export interface Watchlist {
  id: string;
  name: string;
  instruments: string[];
}

export interface WatchlistItem {
  instrument: string;
  display_name: string;
  asset_class: string;
  price_scale: number;
  available: boolean;
  last_price: number | null;
  data_status: string;
  best_setup: {
    id: string;
    timeframe: SetupTimeframe;
    direction: Direction;
    combined: number;
  } | null;
}
