// Inline SVG icons (no icon font or package). All are decorative: the text beside them
// carries the meaning, so each is aria-hidden.

import type { ReactNode } from "react";

type P = { size?: number };

/** The TradeLens mark: three candles over a dashed zone band. */
export function LogoMark({ size = 22 }: P) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <rect
        x="2"
        y="9"
        width="20"
        height="7"
        rx="1.5"
        fill="var(--bull-zone)"
        stroke="var(--bull)"
        strokeDasharray="2 2"
      />
      <rect x="5.5" y="4" width="2.6" height="16" rx="1" fill="var(--bull)" />
      <rect x="10.7" y="7" width="2.6" height="10" rx="1" fill="var(--text)" />
      <rect x="15.9" y="2" width="2.6" height="13" rx="1" fill="var(--primary)" />
    </svg>
  );
}

export function LockIcon({ size = 12 }: P) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" aria-hidden="true" fill="currentColor">
      <path d="M4 7V5a4 4 0 1 1 8 0v2h1a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V8a1 1 0 0 1 1-1h1zm2 0h4V5a2 2 0 1 0-4 0v2z" />
    </svg>
  );
}

export function WarnIcon({ size = 16 }: P) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" aria-hidden="true" fill="var(--warn)">
      <path d="M8 1l7.5 13H.5L8 1zm-.9 5v4h1.8V6H7.1zm0 5v1.8h1.8V11H7.1z" />
    </svg>
  );
}

export function InfoIcon({ size = 16 }: P) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      aria-hidden="true"
      fill="none"
      stroke="var(--primary)"
      strokeWidth="1.6"
    >
      <circle cx="8" cy="8" r="6.5" />
      <path d="M8 7v4.5M8 4.6v.1" />
    </svg>
  );
}

export function ClockIcon({ size = 16 }: P) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      aria-hidden="true"
      fill="none"
      stroke="var(--delayed)"
      strokeWidth="1.6"
    >
      <circle cx="8" cy="8" r="6.5" strokeDasharray="2.5 2" />
      <path d="M8 4.5V8l2.5 1.5" />
    </svg>
  );
}

function Line({ children, size = 24 }: P & { children: ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 28 28"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      aria-hidden="true"
    >
      {children}
    </svg>
  );
}

export function ScanIcon(p: P) {
  return (
    <Line {...p}>
      <path d="M4 7h20M4 14h14M4 21h9" />
      <circle cx="21" cy="20" r="3.5" />
      <path d="M23.5 22.5L26 25" />
    </Line>
  );
}

export function CandleIcon(p: P) {
  return (
    <Line {...p}>
      <path d="M8 4v20M20 3v20" />
      <rect x="5" y="8" width="6" height="10" rx="1" fill="currentColor" fillOpacity=".25" />
      <rect x="17" y="7" width="6" height="8" rx="1" />
    </Line>
  );
}

export function ZoneIcon(p: P) {
  return (
    <Line {...p}>
      <rect x="3" y="12" width="22" height="7" rx="1" fill="var(--fvg)" strokeDasharray="2 2" />
      <path d="M8 5v18M14 8v12M20 4v12" />
    </Line>
  );
}

export function BarsIcon(p: P) {
  return (
    <Line {...p}>
      <rect x="3" y="18" width="5" height="6" />
      <rect x="11.5" y="12" width="5" height="12" />
      <rect x="20" y="5" width="5" height="19" />
    </Line>
  );
}

export function ListIcon(p: P) {
  return (
    <Line {...p}>
      <path d="M10 7h15M10 14h15M10 21h15" />
      <path d="M3.5 7l1.2 1.2L7 5.8M3.5 14l1.2 1.2L7 12.8M3.5 21l1.2 1.2L7 19.8" />
    </Line>
  );
}

export function BellIcon(p: P) {
  return (
    <Line {...p}>
      <path d="M7 19V12a7 7 0 0 1 14 0v7l2 2H5l2-2z" />
      <path d="M11.5 24a2.5 2.5 0 0 0 5 0" />
    </Line>
  );
}

export function MoreIcon(p: P) {
  return (
    <Line {...p}>
      <circle cx="7" cy="14" r="1.6" />
      <circle cx="14" cy="14" r="1.6" />
      <circle cx="21" cy="14" r="1.6" />
    </Line>
  );
}

export function CheckIcon({ size = 14 }: P) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      aria-hidden="true"
      fill="none"
      stroke="var(--bull)"
      strokeWidth="2"
    >
      <path d="M3 8.5l3 3 7-7" />
    </svg>
  );
}

export function DashIcon({ size = 14 }: P) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      aria-hidden="true"
      fill="none"
      stroke="var(--text-2)"
      strokeWidth="1.6"
    >
      <path d="M4 8h8" />
    </svg>
  );
}
