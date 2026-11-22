import { Suspense } from "react";

import { AuthLayout } from "@/components/layout/AuthLayout";
import { ResetPasswordForm } from "@/features/auth/PasswordRecovery";
import { HeroChart } from "@/features/landing/HeroChart";

export const metadata = { title: "Choose a new password · TradeLens" };

export default function Page() {
  return (
    <AuthLayout
      aside={
        <HeroChart label="Example chart with a bullish order block, a fair value gap and a liquidity sweep marked." />
      }
    >
      <Suspense>
        <ResetPasswordForm />
      </Suspense>
    </AuthLayout>
  );
}
