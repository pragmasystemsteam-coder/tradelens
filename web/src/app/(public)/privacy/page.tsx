import { PublicHeader } from "@/components/layout/PublicHeader";
import { Footer } from "@/components/ui/Footer";

export const metadata = { title: "Privacy policy · TradeLens" };

// The full text is published with the public site (task 3.9).
export default function Page() {
  return (
    <>
      <PublicHeader />
      <main className="public-main" id="main">
        <article className="prose">
          <h1>Privacy policy</h1>
          <p className="muted">The full policy is published with the public site.</p>
        </article>
      </main>
      <Footer />
    </>
  );
}
