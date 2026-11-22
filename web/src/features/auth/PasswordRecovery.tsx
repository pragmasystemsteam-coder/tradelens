"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { type FormEvent, useState } from "react";

import { api, ApiError } from "@/lib/api";

const MIN_PASSWORD = 10;

// /forgot-password (FR-ACC-03): one field; the same message whether or not the email exists.
export function ForgotPasswordForm() {
  const [email, setEmail] = useState("");
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("/auth/password/forgot", { method: "POST", body: { email: email.trim() } });
      setDone(true);
    } catch (err) {
      setError(
        err instanceof ApiError && err.code === "rate_limited"
          ? "Too many requests. Try again in a minute."
          : "Could not send the link. Try again shortly.",
      );
    } finally {
      setBusy(false);
    }
  }

  if (done)
    return (
      <section className="login-form" data-testid="forgot-sent">
        <h1>Check your email</h1>
        <p className="muted">
          If an account uses <strong>{email.trim()}</strong>, we sent it a link to choose a new
          password. The link works once, for 1 hour.
        </p>
        <Link className="button button--secondary button--block" href="/login">
          Back to sign in
        </Link>
      </section>
    );

  return (
    <form className="login-form" onSubmit={submit} aria-label="Reset your password">
      <h1>Reset your password</h1>
      <p className="muted">Enter your account email and we will send you a link.</p>
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
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <button type="submit" className="button button--block" disabled={busy}>
        Send the link
      </button>
      <p className="hint">
        Remembered it? <Link href="/login">Sign in</Link>
      </p>
    </form>
  );
}

// /reset-password?token= : a new password; every session of the account is signed out.
export function ResetPasswordForm() {
  const token = useSearchParams().get("token") ?? "";
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [state, setState] = useState<"form" | "done" | "invalid">(token ? "form" : "invalid");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (password.length < MIN_PASSWORD) {
      setError(`Use at least ${MIN_PASSWORD} characters.`);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api("/auth/password/reset", {
        method: "POST",
        body: { token, new_password: password },
      });
      setState("done");
    } catch (err) {
      if (err instanceof ApiError && err.code === "token_invalid") setState("invalid");
      else setError("Could not save the password. Try again shortly.");
    } finally {
      setBusy(false);
    }
  }

  if (state === "done")
    return (
      <section className="login-form" data-testid="reset-done">
        <h1>Password changed</h1>
        <p className="muted">You were signed out on every device. Sign in with the new password.</p>
        <Link className="button button--block" href="/login">
          Sign in
        </Link>
      </section>
    );

  if (state === "invalid")
    return (
      <section className="login-form">
        <h1>This link has expired or was already used</h1>
        <p className="muted">Reset links work once, for 1 hour.</p>
        <Link className="button button--block" href="/forgot-password">
          Send a new link
        </Link>
      </section>
    );

  return (
    <form className="login-form" onSubmit={submit} aria-label="Choose a new password">
      <h1>Choose a new password</h1>
      <div className="field">
        <div className="password-field">
          <label>
            New password
            <input
              name="new_password"
              type={show ? "text" : "password"}
              autoComplete="new-password"
              minLength={MIN_PASSWORD}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              aria-describedby="new-password-hint"
              required
            />
          </label>
          <button type="button" aria-pressed={show} onClick={() => setShow((s) => !s)}>
            {show ? "Hide" : "Show"}
          </button>
        </div>
        <span className="hint" id="new-password-hint">
          At least {MIN_PASSWORD} characters. Saving signs you out everywhere.
        </span>
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <button type="submit" className="button button--block" disabled={busy}>
        Save the new password
      </button>
    </form>
  );
}
