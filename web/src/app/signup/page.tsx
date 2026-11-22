import { AuthLayout } from "@/components/layout/AuthLayout";
import { SignupForm } from "@/features/auth/SignupForm";
import { HeroChart } from "@/features/landing/HeroChart";

export const metadata = { title: "Start free · TradeLens" };
// Read APP_ENV per request: the development-only verification button must never be baked
// into a production build.
export const dynamic = "force-dynamic";

export default function Page() {
  const devLinks = process.env.APP_ENV === "development";
  return (
    <AuthLayout
      aside={
        <>
          <HeroChart label="Example chart with a bullish order block, a fair value gap and a liquidity sweep marked." />
          <ul>
            <li>15 days of Pro after you verify your email. No card needed.</li>
            <li>Then Free: forex majors, scanner and charts, for as long as you like.</li>
            <li>Analytics only. No trades, no advice.</li>
          </ul>
        </>
      }
    >
      <SignupForm devLinks={devLinks} />
    </AuthLayout>
  );
}
