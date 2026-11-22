"use client";

import Link from "next/link";
import { useState } from "react";

import { InfoIcon } from "@/components/ui/Icons";
import { api, ApiError } from "@/lib/api";

// "Check your email" after sign-up or an unverified sign-in (Detailed Design 5.2). `devLinks`
// is true only when the web app runs with APP_ENV=development; the API also refuses the dev
// link outside development, so a production page can never open one.
export function CheckEmail({ email, devLinks }: { email: string; devLinks: boolean }) {
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function resend() {
    setBusy(true);
    setNote(null);
    try {
      await api("/auth/verify/resend", { method: "POST", body: { email } });
      setNote("We sent a new link. The older one no longer works.");
    } catch (err) {
      setNote(
        err instanceof ApiError && err.code === "rate_limited"
          ? "Too many requests. Try again in a minute."
          : "Could not send the link. Try again shortly.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function openDevLink() {
    setBusy(true);
    setNote(null);
    try {
      const { link } = await api<{ link: string }>("/dev/verification-link", {
        method: "POST",
        body: { email },
      });
      const url = new URL(link);
      window.location.assign(url.pathname + url.search);
    } catch {
      setNote("No unverified account with this email, or this is not a development stack.");
      setBusy(false);
    }
  }

  return (
    <section className="login-form" aria-labelledby="check-email-title" data-testid="check-email">
      <h1 id="check-email-title">Check your email</h1>
      <p className="muted">
        We sent a link to <strong>{email}</strong>. Open it to verify your email, then sign in. The
        link works for 24 hours.
      </p>
      <button
        type="button"
        className="button button--secondary button--block"
        onClick={resend}
        disabled={busy}
      >
        Send the link again
      </button>
      {devLinks && (
        <div className="banner banner--warn dev-link" data-testid="dev-link">
          <InfoIcon />
          <div className="dev-link__body">
            <span>Development stack: no email is sent. The worker log has the message.</span>
            <button
              type="button"
              className="button button--ghost"
              onClick={openDevLink}
              disabled={busy}
            >
              Dev: open the verification link
            </button>
          </div>
        </div>
      )}
      {note && (
        <p className="hint" role="status">
          {note}
        </p>
      )}
      <p className="hint">
        Wrong address? <Link href="/signup">Sign up again</Link> · Already verified?{" "}
        <Link href="/login">Sign in</Link>
      </p>
    </section>
  );
}
