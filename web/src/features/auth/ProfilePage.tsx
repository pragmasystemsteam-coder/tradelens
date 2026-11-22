"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useMemo, useState } from "react";

import { useMe, useRefreshMe } from "@/components/layout/AppShell";
import { api, ApiError } from "@/lib/api";

import { TRADING_STYLES, type TradingStyle, timeZones } from "./timezones";

// /account/profile (FR-ACC-04, FR-ACC-06; Detailed Design 5.2 Account): name, time zone,
// trading style and billing country; "Delete my account" needs the password.
export function ProfilePage() {
  const me = useMe();
  const refresh = useRefreshMe();
  const [name, setName] = useState(me.user.name);
  const [zone, setZone] = useState(me.user.timezone);
  const [style, setStyle] = useState<TradingStyle>(me.user.trading_style);
  const [country, setCountry] = useState(me.user.billing_country ?? "");
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const zones = useMemo(() => timeZones([me.user.timezone]), [me.user.timezone]);
  const trialEnd = me.subscription?.status === "trialing" ? me.subscription.trial_ends_at : null;
  const trialEnds = trialEnd
    ? new Intl.DateTimeFormat(undefined, { dateStyle: "long", timeZone: me.user.timezone }).format(
        new Date(trialEnd),
      )
    : null;

  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setNote(null);
    const body: Record<string, string> = {
      name: name.trim(),
      timezone: zone,
      trading_style: style,
    };
    if (country.trim()) body.billing_country = country.trim().toUpperCase();
    try {
      await api("/me", { method: "PATCH", body });
      await refresh();
      setNote("Saved.");
    } catch (err) {
      setNote(
        err instanceof ApiError && err.code === "validation_error"
          ? "Check the fields: the country is two letters, such as IN or US."
          : "Could not save. Try again shortly.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="account-page">
      <h1>Profile and account</h1>
      {trialEnds && (
        <p className="banner banner--pro" data-testid="trial-banner">
          <span>
            Pro trial ends {trialEnds}. After that your account moves to Free; nothing is charged.
          </span>
        </p>
      )}
      <form className="login-form" onSubmit={save} aria-label="Profile">
        <p className="muted">
          Signed in as <strong>{me.user.email}</strong> · Plan: {me.plan.name}
        </p>
        <label>
          Name
          <input
            name="name"
            maxLength={100}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        <label>
          Time zone
          <select name="timezone" value={zone} onChange={(e) => setZone(e.target.value)}>
            {zones.map((z) => (
              <option key={z} value={z}>
                {z}
              </option>
            ))}
          </select>
        </label>
        <div className="field" role="group" aria-labelledby="profile-style">
          <span id="profile-style">How do you trade?</span>
          <div className="seg-buttons seg-buttons--full">
            {TRADING_STYLES.map((s) => (
              <button
                key={s.value}
                type="button"
                aria-pressed={style === s.value}
                onClick={() => setStyle(s.value)}
              >
                {s.label}
              </button>
            ))}
          </div>
        </div>
        <label>
          Billing country
          <input
            name="billing_country"
            maxLength={2}
            placeholder="IN"
            value={country}
            onChange={(e) => setCountry(e.target.value)}
          />
          <span className="hint">Two letters. Picks the currency at checkout.</span>
        </label>
        <button type="submit" className="button" disabled={busy}>
          Save
        </button>
        {note && (
          <p className="hint" role="status">
            {note}
          </p>
        )}
      </form>
      <DeleteAccount />
    </div>
  );
}

function DeleteAccount() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [needsCancel, setNeedsCancel] = useState(false);
  const [cancel, setCancel] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("/me", { method: "DELETE", body: { password, cancel_subscription: cancel } });
      router.replace("/");
    } catch (err) {
      if (err instanceof ApiError && err.code === "subscription_active") {
        setNeedsCancel(true);
        setError("Your paid plan is active. Tick the box to cancel it (no refund), then delete.");
      } else if (err instanceof ApiError && err.code === "invalid_credentials")
        setError("Password is incorrect.");
      else if (err instanceof ApiError && err.code === "forbidden")
        setError("Staff accounts are removed by an admin.");
      else setError("Could not delete the account. Try again shortly.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="danger-zone" aria-labelledby="delete-title">
      <h2 id="delete-title">Delete my account</h2>
      <p className="muted">
        Removes your profile, watchlists, alerts and sessions. Payment records are kept. The free
        trial cannot be used again with this email.
      </p>
      {!open ? (
        <button type="button" className="button button--secondary" onClick={() => setOpen(true)}>
          Delete my account…
        </button>
      ) : (
        <form className="login-form" onSubmit={submit} aria-label="Delete my account">
          <label>
            Password
            <input
              name="delete_password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </label>
          {needsCancel && (
            <label className="check">
              <input
                type="checkbox"
                checked={cancel}
                onChange={(e) => setCancel(e.target.checked)}
              />
              <span>Cancel my paid plan now, with no refund</span>
            </label>
          )}
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          <div className="start-card__actions">
            <button type="submit" className="button button--danger" disabled={busy || !password}>
              Delete permanently
            </button>
            <button type="button" className="button button--ghost" onClick={() => setOpen(false)}>
              Keep my account
            </button>
          </div>
        </form>
      )}
    </section>
  );
}
