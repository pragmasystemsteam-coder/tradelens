// An illustrative H1 chart for the landing page and sign-in panel: a sweep of a low, a break of
// structure up with a fair value gap, then a return to the bullish order block. Static SVG
// drawn from fixed example prices; it is labelled as an example where it is shown.

const CLOSES = [
  1.0868, 1.0861, 1.0864, 1.0855, 1.0849, 1.0852, 1.0843, 1.0838, 1.0841, 1.0832, 1.0818, 1.083,
  1.0861, 1.0889, 1.0896, 1.0909, 1.0902, 1.0911, 1.0898, 1.0886, 1.0872, 1.0858, 1.0846, 1.0838,
  1.0852,
];
const LO = 1.0802;
const HI = 1.0925;
const W = 560;
const H = 280;
const PAD_T = 14;
const PAD_B = 18;
const PAD_L = 8;
const PAD_R = 62;
const STEP = (W - PAD_L - PAD_R) / CLOSES.length;
const BW = STEP * 0.56;
const RIGHT = W - PAD_R;

const y = (p: number) => PAD_T + ((HI - p) / (HI - LO)) * (H - PAD_T - PAD_B);
const x = (i: number) => PAD_L + i * STEP + STEP / 2;

const CANDLES = CLOSES.map((c, i) => {
  const o = i === 0 ? 1.0872 : CLOSES[i - 1];
  const up = c >= o;
  const top = Math.max(o, c) + 0.0003 + (i % 3) * 0.0002;
  const bot = i === 10 ? 1.0808 : Math.min(o, c) - 0.0003 - ((i + 1) % 3) * 0.0002;
  return { i, up, o, c, top, bot };
});

export function HeroChart({ label, animate = false }: { label: string; animate?: boolean }) {
  return (
    <svg
      className={animate ? "hero-draw" : undefined}
      viewBox={`0 0 ${W} ${H}`}
      role="img"
      aria-label={label}
    >
      {[1.082, 1.085, 1.088, 1.091].map((p) => (
        <g key={p}>
          <line className="hz-grid" x1={0} x2={RIGHT + 4} y1={y(p)} y2={y(p)} />
          <text className="hz-txt" x={RIGHT + 8} y={y(p) + 4}>
            {p.toFixed(4)}
          </text>
        </g>
      ))}
      <g className="hz">
        <rect
          className="hz-ob"
          x={x(9) - BW / 2}
          y={y(1.0841)}
          width={RIGHT - x(9) + BW / 2}
          height={y(1.0826) - y(1.0841)}
          rx={2}
        />
        <text className="hz-txt hz-txt--strong" x={x(14)} y={y(1.0826) + 14}>
          Bullish order block
        </text>
        <rect
          className="hz-fvg"
          x={x(12) - BW / 2}
          y={y(1.087)}
          width={RIGHT - x(12) + BW / 2}
          height={y(1.0856) - y(1.087)}
        />
        <text className="hz-txt" x={RIGHT - 6} y={y(1.087) - 5} textAnchor="end">
          Fair value gap
        </text>
        <line className="hz-bos" x1={x(0)} x2={x(15)} y1={y(1.0872)} y2={y(1.0872)} />
        <text className="hz-txt" x={x(1)} y={y(1.0872) - 6}>
          Break of structure
        </text>
        <circle className="hz-sweep" cx={x(10)} cy={y(1.0808)} r={9} />
        <text className="hz-txt" x={x(10) - 14} y={y(1.0808) + 4} textAnchor="end">
          Liquidity sweep
        </text>
      </g>
      {CANDLES.map((k) => (
        <g key={k.i} style={{ ["--i" as string]: k.i }}>
          <line
            className={`hw ${k.up ? "hw-up" : "hw-dn"}`}
            style={{ ["--i" as string]: k.i }}
            x1={x(k.i)}
            x2={x(k.i)}
            y1={y(k.top)}
            y2={y(k.bot)}
            strokeWidth={1.4}
          />
          <rect
            className={`hc ${k.up ? "hc-up" : "hc-dn"}`}
            style={{ ["--i" as string]: k.i }}
            x={x(k.i) - BW / 2}
            y={y(Math.max(k.o, k.c))}
            width={BW}
            height={Math.max(1.5, Math.abs(y(k.o) - y(k.c)))}
            rx={1}
          />
        </g>
      ))}
    </svg>
  );
}
