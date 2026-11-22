import Link from "next/link";
import type { ReactNode } from "react";

import { LockIcon } from "./Icons";

// A Pro-only feature on Free: a lock, a one-line reason and the upgrade link (FR-SUB-12).
export function ProLock({ label, children }: { label: string; children?: ReactNode }) {
  return (
    <div className="pro-lock" data-testid="pro-lock" role="note">
      <span>
        <strong>
          <LockIcon /> Pro
        </strong>{" "}
        {label}
      </span>
      {children}
      <Link className="button button--pro pro-lock__cta" href="/upgrade">
        Upgrade
      </Link>
    </div>
  );
}

/** Small inline lock badge for filter options. */
export function LockBadge() {
  return (
    <span className="lock-badge" data-testid="lock-badge" title="Pro only">
      <LockIcon size={10} /> Pro
    </span>
  );
}
