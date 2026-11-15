import Link from "next/link";

import { type MethodologyAnchor, methodologyHref } from "@/lib/methodology";

// A "?" tooltip that opens the methodology section it refers to (NFR-15).
export function Tip({ anchor, label }: { anchor: MethodologyAnchor; label: string }) {
  return (
    <Link
      className="tip"
      href={methodologyHref(anchor)}
      title={label}
      aria-label={`How ${label} works`}
      data-anchor={anchor}
    >
      ?
    </Link>
  );
}
