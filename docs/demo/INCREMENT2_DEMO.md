# Increment 2 scanner demo (Detailed Design 7.8, "Day 9" checklist)

Run on the development PC (Windows, Git Bash, Docker Desktop running). Make is not installed,
so each recipe is given as the command it runs. Run from the `tradelens` folder.
Time needed: about 30 minutes.

Data source (CR-004): Twelve Data FREE plan. Only EUR/USD and XAU/USD 5m are live; the other
instruments run on synthetic or recorded data. There is no bid/ask on this plan, so spread is 0
and the spread factor always passes. The scripted runs below use synthetic data only and never
call Twelve Data.

Two test accounts: a **Free** user and a **Pro** user. On the full stack create them with
`create-user` (see the Makefile `create-user` recipe; the password is printed once and never
stored). The scripted runs make their own `free@e2e.test` and `pro@e2e.test` with random
passwords that are never shown.

## 0. Automated checks

```bash
.venv/Scripts/python.exe -m pytest -q
```

```bash
MSYS_NO_PATHCONV=1 .venv/Scripts/python.exe scripts/test_db.py
```

Gating with renamed plan codes (FR-SUB-01): the same API tests with `plans.json` codes renamed.

```bash
TL_RENAMED_PLANS=1 MSYS_NO_PATHCONV=1 .venv/Scripts/python.exe scripts/test_db.py backend/tests/integration/api
```

Web app:

```bash
cd web && npm run typecheck && npm run lint && npm run build
```

## 1. E2E-2 and the load check (throwaway stack)

```bash
MSYS_NO_PATHCONV=1 .venv/Scripts/python.exe scripts/e2e.py
```

Expect 5 passed: E2E-2 (Bullish, 1H, score 60+, open the first row, zone highlighted,
disclaimer), `test_reconnect_refetches`, `test_methodology_anchors_exist`, Free locks, 375 px.

```bash
MSYS_NO_PATHCONV=1 .venv/Scripts/python.exe scripts/e2e.py --load
```

Expect `"pass": true`: 100 concurrent scanner loads and 100 SSE streams, p95 under 2 s
(NFR-01, NFR-04).

## 2. Walkthrough with the client (full stack)

Tick each item on screen with the Free user and then the Pro user.

| # | Check | Requirement | Free | Pro |
| --- | --- | --- | --- | --- |
| 1 | Scanner lists bullish and bearish setups for 15m, 1H and 4H with Q, C, combined, patterns, status and data time | FR-SCAN-01..05 | ☐ | ☐ |
| 2 | Each filter narrows the list: instrument, timeframe, direction, pattern, minimum score, session, asset class | FR-SCAN-02 | ☐ | ☐ |
| 3 | A new setup appears within 10 s of a close without reloading (SSE `scanner.updated`) | NFR-01 | ☐ | ☐ |
| 4 | A row opens the chart with the zone highlighted: 500 candles, layer toggles, trend strip, live price, provisional swings, setup panel with explanation and disclaimer | FR-CHART-01..05 | ☐ | ☐ |
| 5 | Watchlist shows best setup and data status | FR-WATCH-02 | ☐ | ☐ |
| 6 | "Data delayed" appears in the scanner, chart and watchlist when a series is delayed | FR-DATA-05 | ☐ | ☐ |
| 7 | Free: Metals and Energy filters locked, commodity chart shows the upgrade card, C factors and higher-timeframe zones show "Pro", history stops at 500 with "Pro shows 2,000" | DD 4.3 | ☐ | — |
| 8 | Pro: commodities listed, higher-timeframe zones on the chart, C factors shown, 2,000 candles | DD 4.3 | — | ☐ |
| 9 | Counter-trend badge, high-quality label at 60, no provisional setup in the list, disclaimer under the scanner filters | FR-MTF-06, 07, FR-SCAN-03, FR-MTF-10 | ☐ | ☐ |
| 10 | Usable at 375 px (browser device mode): bottom tabs, two-line rows, no sideways scroll | NFR-14 | ☐ | ☐ |
| 11 | A third sign-in signs out the oldest session ("signed in on another device") | FR-ACC-05 | ☐ | ☐ |
| 12 | Every "?" opens the matching section of /methodology | NFR-15 | ☐ | ☐ |

To show a delayed series (item 6), stop the network for one ingest pass or use a synthetic gap
as in the Increment 1 demo, then show the badge in all three places.

## Known limits on this data plan

- Spread is 0 (no bid/ask on the Twelve Data free plan); the spread factor is not meaningful yet.
- Live prices are the newest 5m close, not a tick stream, so the price line moves every 5 minutes.
- Custom profiles, alerts, sign-up and billing arrive in Increment 3.
