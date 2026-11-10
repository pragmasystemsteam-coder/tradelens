"""Build a self-contained dev chart page from the golden Twelve Data recordings (task 1.10).

The page is the same Lightweight Charts page as ``GET /dev/chart`` (development only), with the
engine output for EUR/USD and XAU/USD (5m, 15m, 1H, 4H, 1D) embedded, so the engine demo works
without the database or the worker:

    .venv/Scripts/python.exe scripts/dev_chart.py   # writes docs/demo/dev_chart_golden.html

Open the file in a browser (it loads Lightweight Charts 4.2.0 from unpkg).
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from tradelens.integrations.twelvedata.client import parse_time_series
from tradelens.modules.analysis.public import chart_payload, official_settings
from tradelens.modules.market_data.aggregate import aggregate
from tradelens.modules.market_data.calendar import is_expected
from tradelens.modules.market_data.candles import complete_bars, to_stored
from tradelens.modules.market_data.public import load_instrument_specs

REPO = Path(__file__).resolve().parents[1]
GOLDEN = REPO / "engine" / "tests" / "golden"
PAGE = REPO / "backend" / "src" / "tradelens" / "modules" / "analysis" / "dev_chart.html"
OUT = REPO / "docs" / "demo" / "dev_chart_golden.html"
CASES = {"EUR_USD": "td_eurusd_5m_2w.json", "XAU_USD": "td_xauusd_5m_2w.json"}
NOW = datetime(2026, 11, 7, 0, 0, tzinfo=UTC)
DERIVED = (("5m", "15m"), ("5m", "1h"), ("1h", "4h"), ("1h", "1d"))
SHOW = 500


def payloads() -> dict[str, dict[str, object]]:
    """Engine payload per instrument and timeframe, built like the worker builds candles."""
    doc = json.loads((REPO / "config" / "rules" / "r1.0.json").read_text(encoding="utf-8"))
    cfg = official_settings(doc)
    specs = {s.code: s for s in load_instrument_specs(REPO / "config")}
    out: dict[str, dict[str, object]] = {}
    for code, name in CASES.items():
        spec = specs[code]
        body = json.loads((GOLDEN / name).read_text(encoding="utf-8"))
        bars = complete_bars(parse_time_series(body, spec.price_scale), "5m", NOW)
        stored = {"5m": [to_stored(b, code, "5m", "twelvedata") for b in bars
                         if is_expected(spec.calendar, "5m", b.open_time)]}  # fmt: skip
        for source, target in DERIVED:
            stored[target] = aggregate(spec.calendar, source, target, stored[source], NOW)
        out[code] = {tf: chart_payload(rows, code, tf, cfg, doc["version"],
                                       price_scale=spec.price_scale, show=SHOW)
                     for tf, rows in stored.items()}  # fmt: skip
    return out


def main() -> int:
    """Write the page with the payload embedded."""
    html = PAGE.read_text(encoding="utf-8")
    html = html.replace("/*PAYLOAD*/null", json.dumps(payloads(), separators=(",", ":")))
    html = html.replace("<b>TradeLens dev chart</b>",
                        "<b>TradeLens dev chart</b> <span class=\"note\">Twelve Data recording,"
                        " 26 Oct - 6 Nov 2026 (embedded)</span>")  # fmt: skip
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    sys.stdout.write(f"wrote {OUT.relative_to(REPO)} ({OUT.stat().st_size // 1024} KiB)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
