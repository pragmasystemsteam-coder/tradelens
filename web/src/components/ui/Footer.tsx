"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

// Every page footer (Detailed Design 5.2 notices). Signed in, the time zone is the account's;
// on public pages it is the browser's, filled in after the first render.
export function Footer({ timeZone }: { timeZone?: string }) {
  const [local, setLocal] = useState<string | null>(null);
  useEffect(() => {
    if (!timeZone) setLocal(Intl.DateTimeFormat().resolvedOptions().timeZone);
  }, [timeZone]);
  return (
    <footer className="footer" data-testid="footer">
      <nav aria-label="Legal">
        <Link href="/terms">Terms</Link>
        <Link href="/privacy">Privacy</Link>
        <Link href="/methodology">Methodology</Link>
      </nav>
      <p>Analytics only. TradeLens does not place trades or give investment advice.</p>
      <p data-testid="footer-timezone">Times shown in {timeZone ?? local ?? "UTC"}</p>
    </footer>
  );
}
