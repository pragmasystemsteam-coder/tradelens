import { Suspense } from "react";

import { PublicHeader } from "@/components/layout/PublicHeader";
import { Footer } from "@/components/ui/Footer";
import { LoginForm } from "@/features/auth/LoginForm";
import { HeroChart } from "@/features/landing/HeroChart";

export const metadata = { title: "Sign in · TradeLens" };

export default function Page() {
  return (
    <>
      <PublicHeader />
      <main className="auth-layout" id="main">
        <div className="auth-layout__form">
          <Suspense>
            <LoginForm />
          </Suspense>
        </div>
        <aside className="auth-panel" aria-label="About TradeLens">
          <HeroChart label="Example chart with a bullish order block, a fair value gap and a liquidity sweep marked." />
          <ul>
            <li>Order blocks, gaps and sweeps marked by fixed, published rules</li>
            <li>Scores across four timeframes, each with a plain-English reason</li>
            <li>Analytics only. No trades, no advice.</li>
          </ul>
        </aside>
      </main>
      <Footer />
    </>
  );
}
