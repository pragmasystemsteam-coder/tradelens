import { PublicHeader } from "@/components/layout/PublicHeader";
import { Footer } from "@/components/ui/Footer";

export const metadata = { title: "Terms of use · TradeLens" };

// The full text is published with the public site (task 3.9).
export default function Page() {
  return (
    <>
      <PublicHeader />
      <main className="public-main" id="main">
        <article className="prose">
          <h1>Terms of use</h1>
          <p className="muted">The full terms are published with the public site.</p>
          <p className="disclaimer">
            Analytics only. TradeLens does not place trades or give investment advice.
          </p>
        </article>
      </main>
      <Footer />
    </>
  );
}
