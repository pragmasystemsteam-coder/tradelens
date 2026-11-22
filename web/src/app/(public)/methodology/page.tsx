import { PublicHeader } from "@/components/layout/PublicHeader";
import { Footer } from "@/components/ui/Footer";
import { MethodologyPage } from "@/features/methodology/MethodologyPage";

export const metadata = { title: "Methodology · TradeLens" };

export default function Page() {
  return (
    <>
      <PublicHeader />
      <main className="public-main" id="main">
        <MethodologyPage />
      </main>
      <Footer />
    </>
  );
}
