"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { CheckIcon, DashIcon } from "@/components/ui/Icons";
import type { Limits, Price, PublicPlans } from "@/lib/plans";

const ASSET_NAMES: Record<string, string> = {
  forex: "FX pairs",
  metal: "gold and silver",
  energy: "WTI and Brent oil",
};

function money(currency: string, minor: number): string {
  return new Intl.NumberFormat(currency === "INR" ? "en-IN" : "en-US", {
    style: "currency",
    currency,
    minimumFractionDigits: minor % 100 ? 2 : 0,
    maximumFractionDigits: 2,
  }).format(minor / 100);
}

function features(l: Limits, forexPairs: number | null): { on: boolean; text: string }[] {
  const assets = l.asset_classes
    .map((a) =>
      a === "forex" && forexPairs ? `${forexPairs} ${ASSET_NAMES.forex}` : (ASSET_NAMES[a] ?? a),
    )
    .join(", ");
  return [
    { on: true, text: assets.charAt(0).toUpperCase() + assets.slice(1) },
    {
      on: true,
      text:
        l.mtf_detail === "full"
          ? "Full multi-timeframe detail, with reasons"
          : "Multi-timeframe trend strip",
    },
    {
      on: true,
      text: `${l.chart_history_candles.toLocaleString("en-US")} candles of chart history`,
    },
    {
      on: true,
      text: `${l.max_watchlists ?? "Unlimited"} ${l.max_watchlists === 1 ? "watchlist" : "watchlists"}`,
    },
    { on: true, text: `${l.max_alert_rules ?? "Unlimited"} alerts` },
    {
      on: l.custom_settings,
      text: l.custom_settings
        ? `${l.max_profiles} custom scoring profiles`
        : "Custom scoring profiles",
    },
  ];
}

function FeatureList({ items }: { items: { on: boolean; text: string }[] }) {
  return (
    <ul>
      {items.map((f) => (
        <li key={f.text} className={f.on ? undefined : "is-off"}>
          {f.on ? <CheckIcon /> : <DashIcon />}
          <span>
            {!f.on && <span className="sr-only">Not included: </span>}
            {f.text}
          </span>
        </li>
      ))}
    </ul>
  );
}

type Props = { plans: PublicPlans; forexPairs: number | null };

/** Free vs Pro, priced from config/plans.json; INR for visitors in India, USD otherwise. */
export function Pricing({ plans, forexPairs }: Props) {
  const currencies = plans.currencies;
  const [currency, setCurrency] = useState(currencies.includes("USD") ? "USD" : currencies[0]);
  const [interval, setInterval] = useState<Price["interval"]>("month");

  useEffect(() => {
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    if ((tz === "Asia/Kolkata" || tz === "Asia/Calcutta") && currencies.includes("INR"))
      setCurrency("INR");
  }, [currencies]);

  const price = (interval === "month" ? plans.pro.monthly : plans.pro.yearly)[currency];
  const monthly = plans.pro.monthly[currency];
  const saving =
    interval === "year" && price && monthly
      ? Math.round((1 - price.amount_minor / (monthly.amount_minor * 12)) * 100)
      : 0;
  const founder = plans.founder?.prices[currency];
  const trial = plans.pro.trialDays;

  return (
    <>
      <div className="lp-price-head">
        <h2 id="pricing-title">Pricing</h2>
        <div>
          <div className="seg-buttons" role="group" aria-label="Currency">
            {currencies.map((c) => (
              <button
                key={c}
                type="button"
                aria-pressed={currency === c}
                onClick={() => setCurrency(c)}
              >
                {c}
              </button>
            ))}
          </div>
          <div className="seg-buttons" role="group" aria-label="Billing period">
            <button
              type="button"
              aria-pressed={interval === "month"}
              onClick={() => setInterval("month")}
            >
              Monthly
            </button>
            <button
              type="button"
              aria-pressed={interval === "year"}
              onClick={() => setInterval("year")}
            >
              Yearly
            </button>
          </div>
        </div>
      </div>
      <div className="lp-plans">
        <article className="lp-plan" aria-labelledby="plan-free">
          <h3 id="plan-free">{plans.free.name}</h3>
          <div className="lp-plan__amount">
            {money(currency, 0)} <small>forever</small>
          </div>
          <p className="muted">Learn the scanner on the major FX pairs.</p>
          <FeatureList items={features(plans.free.limits, forexPairs)} />
          <Link className="button button--secondary" href="/signup">
            Start free
          </Link>
        </article>
        <article className="lp-plan lp-plan--pro" aria-labelledby="plan-pro">
          <div className="lp-plan__head">
            <h3 id="plan-pro">Pro</h3>
            {trial && <span className="badge badge--pro">{trial}-day free trial</span>}
          </div>
          <div className="lp-plan__amount" aria-live="polite">
            {price ? money(currency, price.amount_minor) : "–"}{" "}
            <small>
              per {interval}
              {saving > 0 && `, ${saving}% less than monthly`}
            </small>
          </div>
          <p className="muted">Commodities, full detail and room for more alerts.</p>
          <FeatureList items={features(plans.pro.limits, forexPairs)} />
          {founder && (
            <p className="lp-founder">
              <b>Founder offer:</b> {money(currency, founder.amount_minor)} per {founder.interval}
              {plans.founder?.cap ? ` for the first ${plans.founder.cap} subscribers` : ""}, then it
              renews at the normal yearly price.
            </p>
          )}
          <Link className="button button--pro" href="/signup">
            {trial ? `Start the ${trial}-day trial` : "Get Pro"}
          </Link>
        </article>
      </div>
    </>
  );
}
