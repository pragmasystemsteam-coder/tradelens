import { Footer } from "@/components/ui/Footer";
import { MethodologyPage } from "@/features/methodology/MethodologyPage";

export const metadata = { title: "Methodology · TradeLens" };

export default function Page() {
  return (
    <>
      <main className="public-main">
        <MethodologyPage />
      </main>
      <Footer />
    </>
  );
}
