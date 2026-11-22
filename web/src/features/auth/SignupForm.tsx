"use client";

import Link from "next/link";
import { type FormEvent, useEffect, useMemo, useState } from "react";

import { api, ApiError } from "@/lib/api";

import { CheckEmail } from "./CheckEmail";
import { TRADING_STYLES, type TradingStyle, detectedTimeZone, timeZones } from "./timezones";

const MIN_PASSWORD = 10;

// Sign up (FR-ACC-01; Detailed Design 5.2): email, password (at least 10), optional name,
// trading style (the scanner's starting timeframe) and the browser's time zone. The API
// answers the same for a new and an existing email, so this always moves to "Check your email".
export function SignupForm({ devLinks }: { devLinks: boolean }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [name, setName] = useState("");
  const [style, setStyle] = useState<TradingStyle>("intraday");
  const [zone, setZone] = useState("UTC");
  const [detected, setDetected] = useState<string | null>(null);
  const [accepted, setAccepted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [sentTo, setSentTo] = useState<string | null>(null);

  useEffect(() => {
    const tz = detectedTimeZone();
    setDetected(tz);
    setZone(tz);
  }, []);
  const zones = useMemo(() => timeZones(detected ? [detected] : []), [detected]);

  const short = password.length > 0 && password.length < MIN_PASSWORD;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (password.length < MIN_PASSWORD) {
      setError(`Use at least ${MIN_PASSWORD} characters for the password.`);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api("/auth/register", {
        method: "POST",
        body: {
          email: email.trim(),
          password,
          name: name.trim(),
          timezone: zone,
          trading_style: style,
        },
      });
      setSentTo(email.trim());
    } catch (err) {
      if (err instanceof ApiError && err.code === "rate_limited")
        setError("Too many sign-ups from this network. Try again in a minute.");
      else if (err instanceof ApiError && err.code === "validation_error")
        setError(validationMessage(err));
      else setError("Could not create the account. Try again shortly.");
    } finally {
      setBusy(false);
    }
  }

  if (sentTo) return <CheckEmail email={sentTo} devLinks={devLinks} />;

  return (
    <form className="login-form" onSubmit={submit} aria-label="Create your free account" noValidate>
      <h1>Create your free account</h1>
      <p className="muted">Verify your email and Pro is yours free for 15 days. No card needed.</p>
      <label>
        Email
        <input
          name="email"
          type="email"
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
        />
      </label>
      <div className="field">
        <div className="password-field">
          <label>
            Password
            <input
              name="password"
              type={showPassword ? "text" : "password"}
              autoComplete="new-password"
              minLength={MIN_PASSWORD}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              aria-invalid={short ? true : undefined}
              aria-describedby="password-hint"
              required
            />
          </label>
          <button
            type="button"
            aria-pressed={showPassword}
            onClick={() => setShowPassword((s) => !s)}
          >
            {showPassword ? "Hide" : "Show"}
          </button>
        </div>
        <span className="hint" id="password-hint">
          At least {MIN_PASSWORD} characters.
        </span>
      </div>
      <label>
        <span>
          Name <span className="hint">(optional)</span>
        </span>
        <input
          name="name"
          autoComplete="name"
          maxLength={100}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </label>
      <div className="field" role="group" aria-labelledby="style-label">
        <span id="style-label">How do you trade?</span>
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
        <span className="hint">Sets the scanner&apos;s starting timeframe. You can change it.</span>
      </div>
      <label>
        Time zone
        <select name="timezone" value={zone} onChange={(e) => setZone(e.target.value)}>
          {zones.map((z) => (
            <option key={z} value={z}>
              {z === detected ? `${z} (detected)` : z}
            </option>
          ))}
        </select>
      </label>
      <label className="check">
        <input
          type="checkbox"
          name="accept"
          checked={accepted}
          onChange={(e) => setAccepted(e.target.checked)}
        />
        <span>
          I accept the <Link href="/terms">Terms</Link> and{" "}
          <Link href="/privacy">Privacy notice</Link>
        </span>
      </label>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <button type="submit" className="button button--block" disabled={busy || !accepted}>
        Create account
      </button>
      <p className="hint">
        Already have an account? <Link href="/login">Sign in</Link>
      </p>
    </form>
  );
}

function validationMessage(err: ApiError): string {
  const errors = (err.details.errors as { field?: string }[] | undefined) ?? [];
  const field = errors[0]?.field ?? "";
  if (field.includes("email")) return "Enter a valid email address.";
  if (field.includes("password"))
    return `Use at least ${MIN_PASSWORD} characters for the password.`;
  if (field.includes("timezone")) return "Pick a time zone from the list.";
  return "Check the form and try again.";
}
