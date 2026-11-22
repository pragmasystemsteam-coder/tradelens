// Public plan data for the landing page, read from config/plans.json at build time (server
// only: it uses the file system). Nothing here hard-codes a price, limit or plan code
// (FR-SUB-01): Free is the default plan, Pro is the paid limit set, the founder offer is the
// paid plan that renews into another.

import { readFileSync } from "node:fs";
import path from "node:path";

export type Limits = {
  asset_classes: string[];
  mtf_detail: "strip" | "full";
  chart_history_candles: number;
  max_watchlists: number | null;
  max_alert_rules: number | null;
  custom_settings: boolean;
  max_profiles: number;
};

export type Price = { amount_minor: number; interval: "month" | "year" };
export type Prices = Record<string, Price>;

export type PublicPlans = {
  free: { name: string; limits: Limits };
  pro: { limits: Limits; trialDays: number | null; monthly: Prices; yearly: Prices };
  founder: { prices: Prices; cap: number | null } | null;
  currencies: string[];
};

type RawPlan = {
  code: string;
  name: string;
  is_paid: boolean;
  is_default?: boolean;
  is_public?: boolean;
  trial_days?: number;
  renews_into?: string;
  founder_cap?: number;
  limits: Limits | string;
  prices?: Prices;
};
type RawDoc = { plans: RawPlan[]; limit_sets: Record<string, Limits> };

function configDir(): string {
  return process.env.CONFIG_DIR ?? path.join(process.cwd(), "..", "config");
}

function plansFile(): string {
  return path.join(configDir(), "plans.json");
}

/** Number of instruments per asset class, from config/instruments.json. */
export function countInstruments(): Record<string, number> {
  const doc = JSON.parse(readFileSync(path.join(configDir(), "instruments.json"), "utf-8")) as {
    instruments: { asset_class: string }[];
  };
  const counts: Record<string, number> = {};
  for (const i of doc.instruments) counts[i.asset_class] = (counts[i.asset_class] ?? 0) + 1;
  return counts;
}

export function loadPublicPlans(): PublicPlans {
  const doc = JSON.parse(readFileSync(plansFile(), "utf-8")) as RawDoc;
  const limitsOf = (p: RawPlan): Limits =>
    typeof p.limits === "string" ? doc.limit_sets[p.limits.replace(/^@/, "")] : p.limits;
  const visible = doc.plans.filter((p) => p.is_public !== false);
  const free = visible.find((p) => p.is_default) ?? visible.find((p) => !p.is_paid);
  const paid = visible.filter((p) => p.is_paid && p.prices);
  const regular = paid.filter((p) => !p.renews_into);
  const byInterval = (interval: Price["interval"]) =>
    regular.find((p) => Object.values(p.prices ?? {}).some((x) => x.interval === interval));
  const monthly = byInterval("month");
  const yearly = byInterval("year");
  const founder = paid.find((p) => p.renews_into);
  if (!free || !monthly || !yearly)
    throw new Error("plans.json: Free, monthly or yearly plan missing");
  const trials = paid.map((p) => p.trial_days ?? 0).filter((d) => d > 0);
  return {
    free: { name: free.name, limits: limitsOf(free) },
    pro: {
      limits: limitsOf(monthly),
      trialDays: trials.length ? Math.max(...trials) : null,
      monthly: monthly.prices ?? {},
      yearly: yearly.prices ?? {},
    },
    founder: founder?.prices ? { prices: founder.prices, cap: founder.founder_cap ?? null } : null,
    currencies: Object.keys(monthly.prices ?? {}),
  };
}
