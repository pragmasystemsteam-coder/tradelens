import type { ReactNode } from "react";

import { PublicHeader } from "@/components/layout/PublicHeader";
import { Footer } from "@/components/ui/Footer";

// Two-column page for sign-up, email verification and password recovery (same frame as
// /login): the form on the left, the product panel on the right (stacks under 768 px).
export function AuthLayout({ children, aside }: { children: ReactNode; aside: ReactNode }) {
  return (
    <>
      <PublicHeader />
      <main className="auth-layout" id="main">
        <div className="auth-layout__form">{children}</div>
        <aside className="auth-panel" aria-label="About TradeLens">
          {aside}
        </aside>
      </main>
      <Footer />
    </>
  );
}
