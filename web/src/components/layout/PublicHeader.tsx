import Link from "next/link";

import { LogoMark } from "@/components/ui/Icons";
import { ThemeSwitch } from "@/components/ui/ThemeSwitch";

// Header for pages that need no sign-in: landing, sign in, sign up, methodology, terms, privacy.
// `sections` adds in-page links (landing only); the actions are always Sign in and Start free.
export function PublicHeader({ sections = false }: { sections?: boolean }) {
  return (
    <header className="public-header">
      <div className="public-header__inner">
        <Link href="/" className="brand">
          <LogoMark /> TradeLens
        </Link>
        {sections && (
          <nav aria-label="Page sections">
            <a href="#features">Features</a>
            <a href="#how-it-works">How it works</a>
            <a href="#pricing">Pricing</a>
            <Link href="/methodology">Methodology</Link>
          </nav>
        )}
        <div className="public-header__actions">
          <ThemeSwitch />
          <Link className="button button--secondary" href="/login">
            Sign in
          </Link>
          <Link className="button" href="/signup">
            Start free
          </Link>
        </div>
      </div>
    </header>
  );
}
