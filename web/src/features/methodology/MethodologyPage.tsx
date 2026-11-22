import Link from "next/link";

import { DISCLAIMER } from "@/components/ui/Disclaimer";
import { METHODOLOGY } from "@/lib/methodology";

function Contents() {
  return (
    <ul>
      {METHODOLOGY.map((m) => (
        <li key={m.id}>
          <a href={`#${m.id}`}>{m.title}</a>
        </li>
      ))}
    </ul>
  );
}

// How TradeLens finds and scores setups: one section per tooltip anchor (NFR-15). A "?" tip
// links to its section, which is highlighted on arrival (:target in globals.css). Contents sit
// in a sticky column from 1,024 px and in a folded list on smaller screens.
export function MethodologyPage() {
  return (
    <div className="doc-layout">
      <nav className="doc-toc" aria-label="Contents">
        <span className="doc-toc__title">On this page</span>
        <Contents />
      </nav>
      <article className="methodology" data-testid="methodology">
        <h1>Methodology</h1>
        <details className="doc-toc-m">
          <summary>Contents ({METHODOLOGY.length})</summary>
          <Contents />
        </details>
        <p className="muted">
          TradeLens applies fixed Smart Money Concepts rules to complete candles only. Every rule,
          score and weight is the same for every user.
        </p>
        <p className="disclaimer">{DISCLAIMER}</p>
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
    </div>
  );
}
