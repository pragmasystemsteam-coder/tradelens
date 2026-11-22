import { Suspense } from "react";

import { AuthLayout } from "@/components/layout/AuthLayout";
import { VerifyEmail } from "@/features/auth/VerifyEmail";
import { HeroChart } from "@/features/landing/HeroChart";

export const metadata = { title: "Verify your email · TradeLens" };

export default function Page() {
  return (
    <AuthLayout
      aside={
        <HeroChart label="Example chart with a bullish order block, a fair value gap and a liquidity sweep marked." />
      }
    >
      <Suspense>
        <VerifyEmail />
      </Suspense>
    </AuthLayout>
  );
}
