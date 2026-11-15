import Link from "next/link";
import type { ReactNode } from "react";

// A Pro-only feature on Free: a lock, a one-line reason and the upgrade link (FR-SUB-12).
export function ProLock({ label, children }: { label: string; children?: ReactNode }) {
  return (
    <div className="pro-lock" data-testid="pro-lock" role="note">
      <span aria-hidden="true">🔒</span> <strong>Pro</strong> {label}
      {children}
      <Link className="pro-lock__cta" href="/upgrade">
        Upgrade
      </Link>
    </div>
  );
}

/** Small inline lock badge for filter options. */
export function LockBadge() {
  return (
    <span className="lock-badge" data-testid="lock-badge" title="Pro only">
      🔒 Pro
    </span>
  );
}
