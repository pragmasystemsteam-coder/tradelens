// FR-MTF-10, NFR-20: shown under the scanner filters, in the setup panel and the watchlist.
export const DISCLAIMER =
  "Scores rank setups by fixed rules. They are not a probability of profit.";

export function Disclaimer() {
  return (
    <p className="disclaimer" data-testid="disclaimer" role="note">
      {DISCLAIMER}
    </p>
  );
}
