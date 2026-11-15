"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { type FormEvent, useState } from "react";

import { api, ApiError } from "@/lib/api";

// Sign in (FR-ACC-02, FR-ACC-05; Detailed Design 5.2 special states).
export function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      await api("/auth/login", { method: "POST", body: { email, password } });
      router.replace("/scanner");
    } catch (err) {
      if (err instanceof ApiError && err.code === "email_not_verified")
        setMessage("Verify your email first");
      else if (err instanceof ApiError && err.code === "rate_limited")
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
          Signed out because your account signed in on another device
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
      <label>
        Password
        <input
          name="password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
      </label>
      {message && (
        <p className="error" role="alert">
          {message}
        </p>
      )}
      <button type="submit" className="button" disabled={busy}>
        Sign in
      </button>
    </form>
  );
}
