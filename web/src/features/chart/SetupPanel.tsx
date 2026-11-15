import { Disclaimer } from "@/components/ui/Disclaimer";
import { ProLock } from "@/components/ui/ProLock";
import { Tip } from "@/components/ui/Tip";
import { formatPrice } from "@/lib/price";
import { formatTime } from "@/lib/time";
import type { SetupDetail } from "@/lib/types";

const FACTOR_NAMES: Record<string, string> = {
  break: "Structure break with displacement",
  sweep: "Liquidity sweep",
  fvg: "Fair value gap in the move",
  ob_fresh: "Fresh order block",
  room: "Room to opposing liquidity",
  spread_session: "Spread and session",
  htf_trend: "Higher-timeframe trend",
  htf_zone: "Inside a higher-timeframe zone",
  ltf_confirm: "Lower-timeframe confirmation",
};

// Score tiles, factors, explanation, levels and times of one setup (Detailed Design 5.2).
export function SetupPanel({ setup, timeZone }: { setup: SetupDetail; timeZone: string }) {
  const scale = setup.price_scale;
  const locked = setup.factors.some((f) => f.locked);
  return (
    <aside className="setup-panel" data-testid="setup-panel" aria-label="Setup">
      <h2>
        {setup.display_name} {setup.direction === "bull" ? "Bullish" : "Bearish"}{" "}
        {setup.timeframe.toUpperCase()}
      </h2>
      <div className="tiles">
        <div className="tile">
          <span>
            Q <Tip anchor="quality-score" label="the quality score" />
          </span>
          <strong>{setup.q}</strong>
        </div>
        <div className="tile">
          <span>
            C <Tip anchor="context-score" label="the context score" />
          </span>
          <strong>{setup.c}</strong>
        </div>
        <div className="tile tile--main">
          <span>
            Combined <Tip anchor="combined-score" label="the combined score" />
          </span>
          <strong data-testid="panel-combined">{setup.combined}</strong>
        </div>
      </div>
      {setup.high_quality && <p className="badge badge--hq">High quality</p>}
      {setup.counter_trend && <p className="badge badge--warn">Counter-trend</p>}
      <ul className="factors" data-testid="factors">
        {setup.factors.map((f) => (
          <li key={f.code} className={f.locked ? "factor factor--locked" : "factor"}>
            <span>{FACTOR_NAMES[f.code] ?? f.code}</span>
            <span>{f.locked ? "Pro" : `${f.points} / ${f.max}`}</span>
          </li>
        ))}
      </ul>
      {locked && <ProLock label="shows the higher-timeframe factor breakdown" />}
      <p className="explanation">{setup.explanation}</p>
      <dl className="levels">
        <dt>Zone</dt>
        <dd data-testid="zone-highlight">
          {formatPrice(setup.zone.low, scale)} – {formatPrice(setup.zone.high, scale)} (
          {setup.zone_state})
        </dd>
        <dt>Invalidation</dt>
        <dd>{formatPrice(setup.invalidation, scale)}</dd>
        <dt>Opposing level</dt>
        <dd>{formatPrice(setup.opposing_level, scale)}</dd>
        <dt>Origin</dt>
        <dd>{formatTime(setup.origin_time, timeZone)}</dd>
        <dt>Confirmed</dt>
        <dd>{formatTime(setup.confirm_time, timeZone)}</dd>
      </dl>
      <Disclaimer />
      <button type="button" className="button" disabled title="Alerts arrive in Increment 3">
        Create alert
      </button>
    </aside>
  );
}
