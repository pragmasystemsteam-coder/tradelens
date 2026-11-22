"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { type FormEvent, useState } from "react";

import { InfoIcon } from "@/components/ui/Icons";
import { api, ApiError } from "@/lib/api";

// Sign in (FR-ACC-02, FR-ACC-05; Detailed Design 5.2 special states).
export function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [unverified, setUnverified] = useState(false);
  const [resent, setResent] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function resend() {
    setBusy(true);
    try {
      await api("/auth/verify/resend", { method: "POST", body: { email: email.trim() } });
      setResent("We sent a new link. Open it, then sign in.");
    } catch {
      setResent("Could not send the link. Try again in a minute.");
    } finally {
      setBusy(false);
    }
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMessage(null);
    setUnverified(false);
    setResent(null);
    try {
      await api("/auth/login", { method: "POST", body: { email, password } });
      router.replace("/scanner");
    } catch (err) {
      if (err instanceof ApiError && err.code === "email_not_verified") {
        setMessage("Verify your email first");
        setUnverified(true);
      } else if (err instanceof ApiError && err.code === "rate_limited")
        setMessage("Too many attempts. Try again in a minute.");
      else setMessage("Email or password is incorrect");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="login-form" onSubmit={submit} aria-label="Sign in">
      <h1>Sign in to TradeLens</h1>
      {params.get("ended") === "1" && (
        <p className="banner banner--info" data-testid="session-ended">
          <InfoIcon />
          <span>Signed out because your account signed in on another device</span>
        </p>
      )}
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
      <div className="password-field">
        <label>
          Password
          <input
            name="password"
            type={showPassword ? "text" : "password"}
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            aria-invalid={message ? true : undefined}
            aria-describedby={message ? "login-error" : undefined}
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
      {message && (
        <p className="error" role="alert" id="login-error">
          {message}
        </p>
      )}
      {unverified && (
        <div className="unverified" data-testid="unverified">
          <button
            type="button"
            className="button button--secondary button--block"
            onClick={resend}
            disabled={busy}
          >
            Send the verification link again
          </button>
          {resent && (
            <p className="hint" role="status">
              {resent}
            </p>
          )}
        </div>
      )}
      <button type="submit" className="button button--block" disabled={busy}>
        Sign in
      </button>
      <p className="hint">
        <Link href="/forgot-password">Forgot your password?</Link>
      </p>
      <p className="hint">
        New to TradeLens? <Link href="/signup">Start free</Link>
      </p>
    </form>
  );
}
