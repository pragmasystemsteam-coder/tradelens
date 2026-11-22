"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useMe } from "@/components/layout/AppShell";

const TIMEFRAMES = new Set(["5m", "15m", "1h", "4h", "1d"]);
const DEFAULT = { instrument: "EUR_USD", timeframe: "1h" };

// "Charts" in the navigation: opens the chart workspace on the chart you used last (saved by
// the workspace on this device), or EUR/USD 1H the first time.
export default function Page() {
  const me = useMe();
  const router = useRouter();
  useEffect(() => {
    let target = DEFAULT;
    try {
      const saved = JSON.parse(
        window.localStorage.getItem(`tl:workspace:v1:${me.user.id}`) ?? "{}",
      ) as { panels?: { instrument?: string; timeframe?: string }[] };
      const first = saved.panels?.[0];
      if (
        first?.instrument &&
        /^[A-Z_]{3,12}$/.test(first.instrument) &&
        first.timeframe &&
        TIMEFRAMES.has(first.timeframe)
      )
        target = { instrument: first.instrument, timeframe: first.timeframe };
    } catch {
      // Nothing saved: use the default chart.
    }
    router.replace(`/chart/${target.instrument}/${target.timeframe}`);
  }, [me.user.id, router]);
  return <div className="loading">Opening charts…</div>;
}
