"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, type ReactNode, useCallback, useContext, useEffect, useState } from "react";

import { Footer } from "@/components/ui/Footer";
import { api, ApiError } from "@/lib/api";
import type { Me } from "@/lib/types";

type Session = { me: Me; refresh: () => Promise<void> };
const SessionContext = createContext<Session | null>(null);

/** The signed-in user, plan and entitlements (from `/me`). */
export function useMe(): Me {
  const session = useContext(SessionContext);
  if (!session) throw new Error("useMe outside AppShell");
  return session.me;
}

const TABS = [
  { href: "/scanner", label: "Scanner" },
  { href: "/watchlists", label: "Watchlists" },
  { href: "/methodology", label: "More" },
];

// Signed-in layout: top bar on desktop, bottom tabs under 768 px (Detailed Design 5.2).
export function AppShell({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [me, setMe] = useState<Me | null>(null);

  const refresh = useCallback(async () => {
    try {
      setMe(await api<Me>("/me"));
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        router.replace(err.code === "session_ended" ? "/login?ended=1" : "/login");
        return;
      }
      throw err;
    }
  }, [router]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function signOut() {
    await api("/auth/logout", { method: "POST" }).catch(() => undefined);
    router.replace("/login");
  }

  if (!me) return <div className="loading">Loading…</div>;
  return (
    <SessionContext.Provider value={{ me, refresh }}>
      <header className="topbar">
        <Link href="/scanner" className="brand">
          TradeLens
        </Link>
        <nav className="topnav" aria-label="Main">
          {TABS.slice(0, 2).map((t) => (
            <Link
              key={t.href}
              href={t.href}
              aria-current={pathname.startsWith(t.href) ? "page" : undefined}
            >
              {t.label}
            </Link>
          ))}
        </nav>
        <span className="plan-chip" data-testid="plan-chip">
          {me.plan.name}
        </span>
        <button type="button" className="link-button" onClick={signOut}>
          Sign out
        </button>
      </header>
      <main className="app-main">{children}</main>
      <Footer timeZone={me.user.timezone} />
      <nav className="bottom-tabs" aria-label="Sections" data-testid="bottom-tabs">
        {TABS.map((t) => (
          <Link
            key={t.href}
            href={t.href}
            aria-current={pathname.startsWith(t.href) ? "page" : undefined}
          >
            {t.label}
          </Link>
        ))}
      </nav>
    </SessionContext.Provider>
  );
}
