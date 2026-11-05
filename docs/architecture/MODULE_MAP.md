# Module map

Ownership and layering from ADR-0001 section 3–4. **Status** says what exists in the code today;
the rest is planned for the increment shown.

| Layer | Module | Owns (tables) | Requirements | Depends on | Status |
| --- | --- | --- | --- | --- | --- |
| 1 | admin | audit log; admin API | FR-ADM-01..11 | lower modules | Increment 3 |
| 1 | monitoring | health checks; `monitor_alert_state` (I3) | FR-ADM-12, NFR-05 | core | **Day 1: `/healthz`** |
| 2 | alerts | `alert_rules`, `alert_deliveries` | FR-ALERT-01..08 | scanner, analysis, billing, notifications | Increment 3 |
| 2 | charts | read-only chart payload | FR-CHART-01..05 | analysis, market_data, billing | Increment 2 |
| 2 | watchlists | `watchlists`, items | FR-WATCH-01..02 | billing, market_data | Increment 2 |
| 3 | scanner | read-only scanner and setup detail | FR-SCAN-01..06 | analysis, billing | Increment 2 |
| 4 | analysis | `rule_versions`, `presets`, `series_state`, `market_events`, `liquidity_levels`, `zones`, `zone_transitions`, `setups`, `setup_revisions` | FR-SMC-01..12, FR-ZONE, FR-MTF, FR-CUST-04/08 | market_data, `tradelens_engine` | **Day 1: rule versions and presets** |
| 4 | customization | profiles and versions | FR-CUST-01..08 | billing | Increment 3 |
| 5 | billing | plans, prices, currency, trial, founder slots/claims, subscriptions, payments, refunds, webhook events | FR-SUB-01..07, FR-ADM refunds | accounts, notifications | Increment 2–3 |
| 6 | accounts | `users`, `sessions`, `email_tokens` | FR-ACC-01..07 | core | Increment 2–3 |
| 6 | market_data | `trading_calendars`, `instruments`, `candles`, `series_status`, `data_gaps` | FR-DATA-01..09 | core | **Day 1: reference data and seed** |
| 6 | realtime | SSE stream, Redis fan-out | FR-SCAN live updates, AD-06/07 | core | Increment 2 |
| 6 | notifications | `email_outbox`, `notifications` | FR-ALERT email/in-app, DD-7 | core | Increment 3 |

Roots: `app/` (API factory and wiring), `worker/` (heartbeat today; scheduler and jobs from task 1.9),
`cli/` (`doctor`, `seed`). Enforcement: `backend/pyproject.toml` import contracts and
`backend/tests/architecture/test_module_boundaries.py`.
