// Prices travel as integers in the smallest unit; divide by 10^price_scale only for display
// (AD-12, Detailed Design 4.1).

export function toNumber(units: number, scale: number): number {
  return units / 10 ** scale;
}

export function formatPrice(units: number | null | undefined, scale: number): string {
  if (units === null || units === undefined) return "—";
  const negative = units < 0;
  const digits = Math.abs(Math.trunc(units))
    .toString()
    .padStart(scale + 1, "0");
  const whole = scale > 0 ? digits.slice(0, -scale) : digits;
  const frac = scale > 0 ? `.${digits.slice(-scale)}` : "";
  return `${negative ? "-" : ""}${whole}${frac}`;
}
