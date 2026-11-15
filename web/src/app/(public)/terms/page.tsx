import { Footer } from "@/components/ui/Footer";

export const metadata = { title: "Terms of use · TradeLens" };

// The full text is published with the public site (task 3.9).
export default function Page() {
  return (
    <>
      <main className="public-main">
        <h1>Terms of use</h1>
        <p>The full terms are published with the public site.</p>
      </main>
      <Footer />
    </>
  );
}
