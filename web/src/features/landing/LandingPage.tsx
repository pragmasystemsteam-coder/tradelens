import Link from "next/link";

import { BarsIcon, BellIcon, ListIcon, ScanIcon, ZoneIcon } from "@/components/ui/Icons";
import { DISCLAIMER } from "@/components/ui/Disclaimer";
import type { PublicPlans } from "@/lib/plans";

import { HeroChart } from "./HeroChart";
import { Pricing } from "./Pricing";
import { ScrollMotion } from "./ScrollMotion";

type Props = { plans: PublicPlans; forexPairs: number | null };

// Public landing page at "/": what TradeLens is, who it is for, features, how it works and
// pricing. No sign-in needed; "Start free" goes to /signup.
export function LandingPage({ plans, forexPairs }: Props) {
  const trial = plans.pro.trialDays;
  return (
    <div className="landing">
      <ScrollMotion />
      <div className="lp-wrap">
        <section className="lp-hero" aria-labelledby="hero-title">
          <div>
            <h1 id="hero-title">Smart Money setups, found and explained.</h1>
            <p className="lp-lede">
              TradeLens scans forex pairs and commodities for order blocks, fair value gaps and
              liquidity sweeps, scores each setup across four timeframes, and tells you in plain
              English why.
            </p>
            <div className="lp-ctas">
              <Link className="button" href="/signup">
                Start free
              </Link>
              <Link className="button button--secondary" href="/login">
                Sign in
              </Link>
            </div>
            <p className="lp-fine">
              The Free plan needs no card.{trial ? ` Pro starts with a ${trial}-day trial.` : ""}
            </p>
          </div>
          <figure className="chart-card" style={{ margin: 0 }}>
            <header>
              <b>EUR/USD H1</b>
              <span className="badge badge--bull">▲ Bullish setup</span>
            </header>
            <HeroChart
              animate
              label="Example H1 chart: price sweeps a low, breaks structure upward, leaves a fair value gap, then comes back to a bullish order block."
            />
            <div className="chart-card__explain">
              <span className="score" aria-label="Example combined score 82">
                82
              </span>
              <p>
                Price took the Asian-session low, then broke structure up and left a fair value gap.
                It is now back in the H1 order block, and H4 and D1 point the same way.
              </p>
            </div>
            <figcaption className="chart-card__credit">Example setup.</figcaption>
          </figure>
        </section>

        <section className="lp-section" aria-labelledby="who-title">
          <h2 id="who-title">For traders who already read structure</h2>
          <div className="lp-who">
            <div>
              <h3>You trade SMC or ICT ideas</h3>
              <p>
                You know what an order block is. You want them marked the same way every time,
                without redrawing charts each morning.
              </p>
            </div>
            <div>
              <h3>You watch many markets</h3>
              <p>
                One ranked list across the FX majors, plus gold, silver and oil on Pro, refreshed on
                every candle close.
              </p>
            </div>
            <div>
              <h3>You make the call</h3>
              <p>
                TradeLens never places a trade or tells you to. It shows the setup and the rules
                behind the score.
              </p>
            </div>
          </div>
        </section>

        <section className="lp-section" id="features" aria-labelledby="features-title">
          <h2 id="features-title">What you get</h2>
          <div className="lp-features">
            <article className="lp-feature lp-feature--wide">
              <ScanIcon size={28} />
              <h3>Scanner</h3>
              <p>
                Every instrument ranked by its best current setup, filtered by timeframe, direction,
                session and asset class.
              </p>
            </article>
            <article className="lp-feature lp-feature--wide">
              <ZoneIcon size={28} />
              <h3>Charts with zones</h3>
              <p>
                Order blocks, fair value gaps, sweeps and breaks of structure drawn on the chart for
                you.
              </p>
            </article>
            <article className="lp-feature">
              <BarsIcon size={28} />
              <h3>Multi-timeframe scores</h3>
              <p>5m to D1 side by side, each score with a plain-English reason.</p>
            </article>
            <article className="lp-feature">
              <ListIcon size={28} />
              <h3>Watchlists</h3>
              <p>Keep the pairs you trade one tap away, with their best setup.</p>
            </article>
            <article className="lp-feature">
              <BellIcon size={28} />
              <h3>Alerts</h3>
              <p>Get told when a setup forms on a pair you follow.</p>
            </article>
          </div>
        </section>

        <section className="lp-section" id="how-it-works" aria-labelledby="how-title">
          <h2 id="how-title">How it works</h2>
          <ol className="lp-steps">
            <li>
              <h3>Candles close</h3>
              <p>On every candle close, fresh prices come in for each instrument.</p>
            </li>
            <li>
              <h3>Rules find structure</h3>
              <p>Fixed, published rules mark sweeps, breaks, order blocks and gaps.</p>
            </li>
            <li>
              <h3>Setups are scored</h3>
              <p>Each setup gets 0–100 for how many timeframes and conditions agree.</p>
            </li>
            <li>
              <h3>You review and decide</h3>
              <p>Open the chart, read the reasons, and trade your own plan.</p>
            </li>
          </ol>
        </section>

        <section className="lp-section" id="pricing" aria-labelledby="pricing-title">
          <Pricing plans={plans} forexPairs={forexPairs} />
        </section>

        <section className="lp-legal" aria-label="Notices">
          <p>
            <strong>
              Analytics only. TradeLens does not place trades or give investment advice.
            </strong>
          </p>
          <p>
            {DISCLAIMER} Read how every score is built in the{" "}
            <Link href="/methodology">methodology</Link>.
          </p>
        </section>
      </div>
    </div>
  );
}
