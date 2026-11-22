import { AuthLayout } from "@/components/layout/AuthLayout";
import { ForgotPasswordForm } from "@/features/auth/PasswordRecovery";
import { HeroChart } from "@/features/landing/HeroChart";

export const metadata = { title: "Reset your password · TradeLens" };

export default function Page() {
  return (
    <AuthLayout
      aside={
        <HeroChart label="Example chart with a bullish order block, a fair value gap and a liquidity sweep marked." />
      }
    >
      <ForgotPasswordForm />
    </AuthLayout>
  );
}
