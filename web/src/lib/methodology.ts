// Every tooltip in the app links to one of these anchors on /methodology (NFR-15).
// The methodology page renders a section per anchor; E2E-2 checks they all exist.

export const METHODOLOGY = [
  {
    id: "quality-score",
    title: "Quality score (Q)",
    text: "Q (0 to 100) rates the setup on its own timeframe: a structure break with displacement (25), a liquidity sweep before it (20), a fair value gap in the move (20), a fresh order block (15), room to the opposing liquidity (15) and spread and session (5).",
  },
  {
    id: "context-score",
    title: "Context score (C)",
    text: "C (0 to 100) rates how the higher timeframes agree: their trend (40), whether the zone sits inside a higher-timeframe zone (30) and a lower-timeframe confirmation after the zone is touched (30).",
  },
  {
    id: "combined-score",
    title: "Combined score",
    text: "Combined = 60% of Q plus 40% of C, rounded half up. Setups are ranked by it. Scores rank setups by fixed rules. They are not a probability of profit.",
  },
  {
    id: "high-quality",
    title: "High quality",
    text: "A setup with a combined score of 60 or more is labelled high quality.",
  },
  {
    id: "counter-trend",
    title: "Counter-trend",
    text: "The setup goes against the higher-timeframe trend. It is shown with a warning badge.",
  },
  {
    id: "bos",
    title: "Break of structure (BOS)",
    text: "A candle closes beyond the last unbroken swing in the direction of the trend.",
  },
  {
    id: "choch",
    title: "Change of character (CHoCH)",
    text: "A candle closes beyond the protected swing against the trend, so the trend changes.",
  },
  {
    id: "displacement",
    title: "Displacement",
    text: "One strong candle, or two or three in the same direction, that move at least 1.5 to 2 times the average true range.",
  },
  {
    id: "fvg",
    title: "Fair value gap (FVG)",
    text: "A three-candle gap: the third candle's low is above the first candle's high (bullish), or the mirror (bearish).",
  },
  {
    id: "order-block",
    title: "Order block (OB)",
    text: "The last opposite candle before a displacement that broke structure within three candles.",
  },
  {
    id: "liquidity-sweep",
    title: "Liquidity sweep",
    text: "A wick beyond a liquidity level with the close back inside on the same candle.",
  },
  {
    id: "liquidity",
    title: "Liquidity levels",
    text: "Swing highs and lows, equal highs and lows, the previous day and week, and the Asian, London and New York session highs and lows. A level ends when it is swept, broken, superseded, merged or too old.",
  },
  {
    id: "zone-states",
    title: "Zone states",
    text: "A zone is confirmed, then may be touched, 50% mitigated, filled, invalidated (a close beyond the far edge) or expired (too old or retested too often).",
  },
  {
    id: "provisional",
    title: "Provisional swings",
    text: "Pending pivots that have not yet had enough candles on the right. They are drawn dashed and are never scored, listed or alerted.",
  },
  {
    id: "sessions",
    title: "Sessions",
    text: "Asian 19:00 to 03:00, London 03:00 to 12:00 and New York 08:00 to 17:00, New York time. The trading day closes at 17:00 New York.",
  },
  {
    id: "timeframes",
    title: "Timeframes and profiles",
    text: "15m is the Scalping profile (1H context, 5m confirmation), 1H is Intraday (1D and 4H context, 15m and 5m confirmation) and 4H is Swing (1D context, 1H confirmation).",
  },
  {
    id: "trend-strip",
    title: "Trend strip",
    text: "The internal and external trend of the 1D, 4H, 1H, 15m and 5m series, as of their last closed candle.",
  },
  {
    id: "data-delayed",
    title: "Data delayed",
    text: "A series missed a candle. TradeLens keeps the last good data, marks it delayed and catches up when the data returns.",
  },
] as const;

export type MethodologyAnchor = (typeof METHODOLOGY)[number]["id"];

export function methodologyHref(id: MethodologyAnchor): string {
  return `/methodology#${id}`;
}
