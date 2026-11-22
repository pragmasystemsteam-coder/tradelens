"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";

import { Footer } from "@/components/ui/Footer";
import {
  CandleIcon,
  ListIcon,
  LockIcon,
  LogoMark,
  MoreIcon,
  ScanIcon,
} from "@/components/ui/Icons";
import { ThemeSwitch } from "@/components/ui/ThemeSwitch";
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

/** Reloads `/me` after the profile changes (account page). */
export function useRefreshMe(): () => Promise<void> {
  const session = useContext(SessionContext);
  if (!session) throw new Error("useRefreshMe outside AppShell");
  return session.refresh;
}

// Each live stream on the page reports its state here; the top bar shows "Reconnecting…"
// while any of them is down.
const LiveContext = createContext<(id: string, connected: boolean) => void>(() => undefined);

/** Returns the callback a page passes as the stream's `onStateChange`. */
export function useReportLive(): (connected: boolean) => void {
  const report = useContext(LiveContext);
  const id = useId();
  useEffect(() => () => report(id, true), [report, id]);
  return useCallback((connected: boolean) => report(id, connected), [report, id]);
}

const TABS = [
  { href: "/scanner", label: "Scanner", icon: ScanIcon },
  { href: "/chart", label: "Charts", icon: CandleIcon },
  { href: "/watchlists", label: "Watchlists", icon: ListIcon },
  { href: "/methodology", label: "More", icon: MoreIcon },
];

function trialDaysLeft(me: Me): number | null {
  const ends = me.subscription?.status === "trialing" ? me.subscription.trial_ends_at : null;
  if (!ends) return null;
  return Math.max(0, Math.ceil((Date.parse(ends) - Date.now()) / 86_400_000));
}

function initials(me: Me): string {
  const source = me.user.name?.trim() || me.user.email;
  const parts = source.split(/[\s@._-]+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase() || "?";
}

// Signed-in layout: sticky top bar on tablet and up, bottom tabs under 768 px (Detailed Design 5.2).
export function AppShell({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [me, setMe] = useState<Me | null>(null);
  const [down, setDown] = useState<Set<string>>(new Set());
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const menuId = useId();

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

  const reportLive = useCallback((id: string, connected: boolean) => {
    setDown((cur) => {
      if (connected === !cur.has(id)) return cur;
      const next = new Set(cur);
      if (connected) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  useEffect(() => {
    if (!menuOpen) return;
    const onDown = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMenuOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [menuOpen]);

  useEffect(() => setMenuOpen(false), [pathname]);

  async function signOut() {
    await api("/auth/logout", { method: "POST" }).catch(() => undefined);
    router.replace("/login");
  }

  if (!me) return <div className="loading">Loading…</div>;
  const isPro = me.entitlements.mtf_detail === "full";
  const trial = trialDaysLeft(me);
  const live = down.size === 0;
  return (
    <SessionContext.Provider value={{ me, refresh }}>
      <LiveContext.Provider value={reportLive}>
        <a className="skip-link" href="#main">
          Skip to content
        </a>
        <header className="topbar">
          <Link href="/scanner" className="brand">
            <LogoMark /> TradeLens
          </Link>
          <nav className="topnav" aria-label="Main">
            {TABS.map((t) => (
              <Link
                key={t.href}
                href={t.href}
                aria-current={pathname.startsWith(t.href) ? "page" : undefined}
              >
                {t.label === "More" ? "Methodology" : t.label}
              </Link>
            ))}
          </nav>
          <span className={live ? "live" : "live live--down"} role="status">
            <i className="live__dot" aria-hidden="true" />
            <span className="live__label">{live ? "Live" : "Reconnecting…"}</span>
            <span className="sr-only">{live ? "" : "Live updates paused"}</span>
          </span>
          <span
            className={isPro ? "plan-chip plan-chip--pro" : "plan-chip"}
            data-testid="plan-chip"
          >
            {me.plan.name}
            {trial !== null && `, ${trial} ${trial === 1 ? "day" : "days"} left`}
          </span>
          {!isPro && (
            <Link className="upgrade-link" href="/upgrade">
              <LockIcon /> Upgrade
            </Link>
          )}
          <div className="account" ref={menuRef}>
            <button
              type="button"
              className="avatar"
              aria-label="Account and settings"
              aria-expanded={menuOpen}
              aria-controls={menuId}
              onClick={() => setMenuOpen((o) => !o)}
            >
              {initials(me)}
            </button>
            {menuOpen && (
              <div className="account-menu" id={menuId}>
                <span className="account-menu__email">{me.user.email}</span>
                <div className="account-menu__row">
                  Theme <ThemeSwitch />
                </div>
                <span className="account-menu__row muted">Time zone: {me.user.timezone}</span>
                <Link className="link-button" href="/account/profile">
                  Profile and account
                </Link>
                <Link className="link-button" href="/methodology">
                  How scores work
                </Link>
                <button type="button" className="link-button" onClick={signOut}>
                  Sign out
                </button>
              </div>
            )}
          </div>
        </header>
        <main className="app-main" id="main">
          {children}
        </main>
        <Footer timeZone={me.user.timezone} />
        <nav className="bottom-tabs" aria-label="Sections" data-testid="bottom-tabs">
          {TABS.map((t) => {
            const Icon = t.icon;
            return (
              <Link
                key={t.href}
                href={t.href}
                aria-current={pathname.startsWith(t.href) ? "page" : undefined}
              >
                <Icon size={22} />
                <span>{t.label}</span>
              </Link>
            );
          })}
        </nav>
      </LiveContext.Provider>
    </SessionContext.Provider>
  );
}
