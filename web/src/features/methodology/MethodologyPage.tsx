import Link from "next/link";

import { DISCLAIMER } from "@/components/ui/Disclaimer";
import { METHODOLOGY } from "@/lib/methodology";

// How TradeLens finds and scores setups: one section per tooltip anchor (NFR-15).
export function MethodologyPage() {
  return (
    <article className="methodology" data-testid="methodology">
      <h1>Methodology</h1>
      <p>
        TradeLens applies fixed Smart Money Concepts rules to complete candles only. Every rule,
        score and weight is the same for every user. {DISCLAIMER}
      </p>
      <nav aria-label="Contents">
        <ul>
          {METHODOLOGY.map((m) => (
            <li key={m.id}>
              <a href={`#${m.id}`}>{m.title}</a>
            </li>
          ))}
        </ul>
      </nav>
      {METHODOLOGY.map((m) => (
        <section key={m.id} id={m.id} aria-labelledby={`${m.id}-title`}>
          <h2 id={`${m.id}-title`}>{m.title}</h2>
          <p>{m.text}</p>
        </section>
      ))}
      <p>
        <Link href="/scanner">Back to the scanner</Link>
      </p>
    </article>
  );
}
