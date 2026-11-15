import Link from "next/link";

// Every page footer (Detailed Design 5.2 notices).
export function Footer({ timeZone }: { timeZone?: string }) {
  return (
    <footer className="footer" data-testid="footer">
      <nav aria-label="Legal">
        <Link href="/terms">Terms</Link>
        <Link href="/privacy">Privacy</Link>
        <Link href="/methodology">Methodology</Link>
      </nav>
      <p>Analytics only. TradeLens does not place trades or give investment advice.</p>
      <p data-testid="footer-timezone">Times shown in {timeZone ?? "UTC"}</p>
    </footer>
  );
}
