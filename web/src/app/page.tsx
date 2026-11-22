import { PublicHeader } from "@/components/layout/PublicHeader";
import { Footer } from "@/components/ui/Footer";
import { LandingPage } from "@/features/landing/LandingPage";
import { countInstruments, loadPublicPlans } from "@/lib/plans";

// Built once at build time from config/plans.json and config/instruments.json.
export const dynamic = "force-static";

export default function Home() {
  const plans = loadPublicPlans();
  const forexPairs = countInstruments().forex ?? null;
  return (
    <>
      <PublicHeader sections />
      <main id="main">
        <LandingPage plans={plans} forexPairs={forexPairs} />
      </main>
      <Footer />
    </>
  );
}
