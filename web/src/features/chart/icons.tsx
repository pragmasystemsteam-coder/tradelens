// Workspace icons (inline SVG, decorative: every control has its own text label).
import type { ReactNode } from "react";

function I({ children, size = 18 }: { children: ReactNode; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  );
}

export const ToolIcons = {
  select: (
    <I>
      <path d="M5 3l10 6-4.5 1.5L13 16l-2 1-2.5-5.5L5 15z" />
    </I>
  ),
  trend: (
    <I>
      <path d="M3 16L17 4" />
      <circle cx="3.5" cy="15.5" r="1.5" fill="currentColor" />
      <circle cx="16.5" cy="4.5" r="1.5" fill="currentColor" />
    </I>
  ),
  hline: (
    <I>
      <path d="M2 10h16" />
      <circle cx="10" cy="10" r="1.5" fill="currentColor" />
    </I>
  ),
  ray: (
    <I>
      <path d="M4 15L18 6" />
      <circle cx="4.5" cy="14.5" r="1.5" fill="currentColor" />
    </I>
  ),
  rect: (
    <I>
      <rect x="3" y="6" width="14" height="8" strokeDasharray="2 2" />
    </I>
  ),
  fib: (
    <I>
      <path d="M3 4h14M3 8h14M3 11h14M3 16h14M3 4v12" />
    </I>
  ),
  text: (
    <I>
      <path d="M5 5h10M10 5v11" />
    </I>
  ),
  measure: (
    <I>
      <path d="M3 15L15 3l2 2L5 17z" />
      <path d="M7 11l1.5 1.5M10 8l1.5 1.5M13 5l1.5 1.5" />
    </I>
  ),
  undo: (
    <I>
      <path d="M7 5L3 9l4 4" />
      <path d="M3 9h9a4 4 0 0 1 0 8h-2" />
    </I>
  ),
  redo: (
    <I>
      <path d="M13 5l4 4-4 4" />
      <path d="M17 9H8a4 4 0 0 0 0 8h2" />
    </I>
  ),
  lock: (
    <I>
      <rect x="4" y="9" width="12" height="8" rx="1" />
      <path d="M7 9V6a3 3 0 0 1 6 0v3" />
    </I>
  ),
  eye: (
    <I>
      <path d="M2 10s3-5 8-5 8 5 8 5-3 5-8 5-8-5-8-5z" />
      <circle cx="10" cy="10" r="2.5" />
    </I>
  ),
  eyeOff: (
    <I>
      <path d="M2 10s3-5 8-5 8 5 8 5-3 5-8 5-8-5-8-5z" />
      <path d="M3 3l14 14" />
    </I>
  ),
  trash: (
    <I>
      <path d="M4 6h12M8 6V4h4v2M6 6l1 11h6l1-11" />
    </I>
  ),
  erase: (
    <I>
      <path d="M8 16h9M4 12l7-7 5 5-6 6H7z" />
    </I>
  ),
};

export const UiIcons = {
  full: (
    <I>
      <path d="M3 8V3h5M17 8V3h-5M3 12v5h5M17 12v5h-5" />
    </I>
  ),
  exitFull: (
    <I>
      <path d="M8 3v5H3M12 3v5h5M8 17v-5H3M12 17v-5h5" />
    </I>
  ),
  side: (
    <I>
      <rect x="3" y="3" width="14" height="14" rx="1" />
      <path d="M12 3v14" />
    </I>
  ),
  link: (
    <I>
      <path d="M8 12l4-4M7 9l-2 2a2.8 2.8 0 0 0 4 4l2-2M13 11l2-2a2.8 2.8 0 0 0-4-4l-2 2" />
    </I>
  ),
  layers: (
    <I>
      <path d="M10 3l7 4-7 4-7-4z" />
      <path d="M3 11l7 4 7-4" />
    </I>
  ),
  tools: (
    <I>
      <path d="M3 16L17 4" />
      <path d="M3 4h5M3 8h3" />
    </I>
  ),
  close: (
    <I>
      <path d="M5 5l10 10M15 5L5 15" />
    </I>
  ),
};

export const StyleIcons = {
  candles: (
    <I>
      <path d="M6 3v14M14 3v14" />
      <rect x="4" y="6" width="4" height="7" fill="currentColor" />
      <rect x="12" y="8" width="4" height="5" fill="currentColor" />
    </I>
  ),
  hollow: (
    <I>
      <path d="M6 3v14M14 3v14" />
      <rect x="4" y="6" width="4" height="7" fill="var(--bg)" />
      <rect x="12" y="8" width="4" height="5" fill="currentColor" />
    </I>
  ),
  bars: (
    <I>
      <path d="M6 3v14M3 6h3M6 13h3M14 4v13M11 8h3M14 14h3" />
    </I>
  ),
  line: (
    <I>
      <path d="M2 15l5-5 4 3 7-8" />
    </I>
  ),
  area: (
    <I>
      <path d="M2 15l5-5 4 3 7-8v13H2z" fill="currentColor" fillOpacity=".25" />
    </I>
  ),
  heikin: (
    <I>
      <path d="M6 3v14M14 3v14" />
      <rect x="4" y="5" width="4" height="9" rx="1" fill="currentColor" />
      <rect x="12" y="7" width="4" height="7" rx="1" fill="currentColor" />
    </I>
  ),
};

export function LayoutIcon({ layout }: { layout: "1" | "2h" | "2v" | "4" }) {
  const cells: Record<string, string[]> = {
    "1": ["M3 3h14v14H3z"],
    "2h": ["M3 3h6v14H3z", "M11 3h6v14h-6z"],
    "2v": ["M3 3h14v6H3z", "M3 11h14v6H3z"],
    "4": ["M3 3h6v6H3z", "M11 3h6v6h-6z", "M3 11h6v6H3z", "M11 11h6v6h-6z"],
  };
  return (
    <I>
      {cells[layout].map((d) => (
        <path key={d} d={d} />
      ))}
    </I>
  );
}
