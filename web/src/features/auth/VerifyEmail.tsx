"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { type FormEvent, useEffect, useRef, useState } from "react";

import { api, ApiError } from "@/lib/api";

type State =
  { kind: "working" } | { kind: "done"; trial: boolean } | { kind: "invalid" } | { kind: "error" };

// /verify-email?token= (Detailed Design 5.2): spends the link once, then offers Sign in.
// An expired or used link offers a new one.
export function VerifyEmail() {
  const token = useSearchParams().get("token") ?? "";
  const [state, setState] = useState<State>({ kind: "working" });
  const sent = useRef(false); // the token works once: never post it twice (React dev re-runs)

  useEffect(() => {
    if (sent.current) return;
    sent.current = true;
    if (!token) {
      setState({ kind: "invalid" });
      return;
    }
    api<{ trial_started: boolean }>("/auth/verify", { method: "POST", body: { token } })
      .then((r) => setState({ kind: "done", trial: r.trial_started }))
      .catch((err) =>
        setState(
          err instanceof ApiError && err.code === "token_invalid"
            ? { kind: "invalid" }
            : { kind: "error" },
        ),
      );
  }, [token]);

  if (state.kind === "working")
    return (
      <section className="login-form" aria-busy="true">
        <h1>Verifying your email…</h1>
      </section>
    );

  if (state.kind === "done")
    return (
      <section className="login-form" data-testid="verify-done">
        <h1>Your email is verified</h1>
        {state.trial ? (
          <p className="banner banner--pro" data-testid="trial-started">
            <span>
              <strong>Your 15-day Pro trial has started.</strong> Metals, energy and full
              multi-timeframe detail are open until it ends. Nothing is charged.
            </span>
          </p>
        ) : (
          <p className="muted">Your account is on the Free plan.</p>
        )}
        <Link className="button button--block" href="/login">
          Sign in
        </Link>
      </section>
    );

  return <ResendLink failed={state.kind === "error"} />;
}

function ResendLink({ failed }: { failed: boolean }) {
  const [email, setEmail] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await api("/auth/verify/resend", { method: "POST", body: { email: email.trim() } });
      setNote("If that account still needs verifying, a new link is on its way.");
    } catch {
      setNote("Could not send the link. Try again in a minute.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="login-form" onSubmit={submit} aria-label="Send a new link">
      <h1>{failed ? "Something went wrong" : "This link has expired or was already used"}</h1>
      <p className="muted">
        {failed
          ? "We could not check the link. Try it again, or ask for a new one."
          : "Links work once and for 24 hours. Already verified? Sign in. Otherwise ask for a new link."}
      </p>
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
      <button type="submit" className="button button--block" disabled={busy}>
        Send a new link
      </button>
      {note && (
        <p className="hint" role="status">
          {note}
        </p>
      )}
      <p className="hint">
        <Link href="/login">Sign in</Link>
      </p>
    </form>
  );
}
