import { Footer } from "@/components/ui/Footer";

export const metadata = { title: "Privacy policy · TradeLens" };

// The full text is published with the public site (task 3.9).
export default function Page() {
  return (
    <>
      <main className="public-main">
        <h1>Privacy policy</h1>
        <p>The full policy is published with the public site.</p>
      </main>
      <Footer />
    </>
  );
}
