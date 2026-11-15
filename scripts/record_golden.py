"""Record two weeks of real 5m history from Twelve Data as golden fixtures (DD 8.1 task 1.10).

One ``/time_series`` call per instrument (outputsize 5000 = 1 credit each, about 2 credits in
all; the FREE plan allows 8 a minute and 800 a day). The API key is read from deploy/.env
inside this process and never printed or written anywhere. The bodies are saved unchanged
(plus a ``_comment``) to engine/tests/golden/, so the recording pins the input:

    .venv/Scripts/python.exe scripts/record_golden.py

Run it again only to replace the recording on purpose; then review and rewrite the expected
events with ``backend/tests/unit/analysis/golden_twelvedata.py --write``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "engine" / "tests" / "golden"
BASE_URL = "https://api.twelvedata.com"
START, END = "2026-10-26 00:00:00", "2026-11-07 00:00:00"  # two trading weeks, US DST change
RECORDINGS = {  # instrument: (symbol, price scale, file)
    "EUR_USD": ("EUR/USD", 5, "td_eurusd_5m_2w.json"),
    "XAU_USD": ("XAU/USD", 3, "td_xauusd_5m_2w.json"),
}
TIMEOUT_SECONDS = 30.0


def api_key(env_file: Path) -> str:
    """TWELVEDATA_API_KEY from the env file (the value is never echoed)."""
    for line in env_file.read_text(encoding="utf-8").splitlines():
        name, _, value = line.partition("=")
        if name.strip() == "TWELVEDATA_API_KEY" and value.strip():
            return value.strip()
    raise SystemExit("TWELVEDATA_API_KEY is not set in deploy/.env")


def main() -> int:
    """Record every instrument; print only counts, field names and credit headers."""
    key = api_key(REPO / "deploy" / ".env")
    OUT.mkdir(parents=True, exist_ok=True)
    with httpx.Client(base_url=BASE_URL, timeout=TIMEOUT_SECONDS) as http:
        for instrument, (symbol, scale, name) in RECORDINGS.items():
            params = {"symbol": symbol, "interval": "5min", "start_date": START,
                      "end_date": END, "timezone": "UTC", "order": "ASC", "dp": str(scale),
                      "outputsize": "5000"}  # fmt: skip
            response = http.get("/time_series", params=params,
                                headers={"Authorization": f"apikey {key}"})  # fmt: skip
            body = response.json()
            if response.status_code != httpx.codes.OK or body.get("status") != "ok":
                error = f"{instrument}: HTTP {response.status_code} {body.get('message')}"
                sys.stderr.write(error + "\n")
                return 1
            values = body["values"]
            note = (f"Twelve Data /time_series {symbol} 5min {START} to {END} UTC, recorded"
                    " 10 Nov 2026 for test_golden_events (task 1.10).")  # fmt: skip
            body = {"_comment": note, **body}
            (OUT / name).write_text(json.dumps(body, indent=1) + "\n", encoding="utf-8")
            credits = {k: v for k, v in response.headers.items() if "credits" in k.lower()}
            span = f"{values[0]['datetime']} .. {values[-1]['datetime']}"
            sys.stdout.write(f"{instrument}: {len(values)} bars {span}; "
                             f"fields {sorted(values[0])}; {credits}\n")  # fmt: skip
    return 0


if __name__ == "__main__":
    sys.exit(main())
