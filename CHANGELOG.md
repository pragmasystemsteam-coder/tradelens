# Changelog

All notable changes to TradeLens. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow the increments (0.1 = Increment 1, 0.2 = Increment 2, 1.0 = Release 1 handover).

## [Unreleased]

### Added (Day 5, 15 Nov 2026)
- Worker setups and revisions with each close batch, batch-end re-evaluation, Redis scanner cache and
  `scanner.updated` (task 2.3; migration 0003 `setups.engine`).
- API foundation: DD 4.1 error body, request IDs, `__Host-` session and CSRF cookies (HMAC-stored, 7-day sliding
  idle, 2 sessions), Origin and CSRF checks, Redis rate limits, entitlements from limit keys only (cached 60 s),
  `/auth/login`, `/auth/logout`, `/me` (task 2.4).
- `/setups`, `/setups/{id}`, `/instruments`, `/prices`, `/status/data` (task 2.5); `/charts`, `/candles` with on-demand
  preset compute (thread pool, 15-minute cache, 20/min) (task 2.6); watchlists (task 2.7); SSE `/stream` (task 2.8).
- Customer web app: sign-in, scanner, chart (Lightweight Charts v5 overlays), setup panel, watchlists, methodology,
  phone layout; ESLint feature boundaries; Playwright E2E-2 via `scripts/e2e.py` (task 2.9).
- `scripts/loadcheck.py`, renamed-plan-codes gating rerun, Day 9 demo checklist `docs/demo/INCREMENT2_DEMO.md`;
  Makefile `e2e`, `loadcheck`, `test-db-renamed-plans` (task 2.10).

### Changed (Day 5)
- Request-validation errors answer 400 `validation_error` (was FastAPI's 422), per DD 4.1.
- Caddy overwrites `X-Forwarded-For` with the resolved client IP on API routes.
- The API refuses to start outside development/test without two different secrets of 32+ characters.
- `worker/main.py` builds the scorer through `analysis.scorer_for` (only analysis imports the engine).
- API database pool 10 + 30 connections with a matching worker-thread limit and an async admission gate; every
  database dependency commits before the response is sent.

### Added (Day 4, 10 Nov 2026)
- Worker candle-close pipeline (task 1.9): ingest, engine `step_batch` per instrument (highest timeframe first),
  events and state in one transaction, delayed series never stepped, restart from `series_state`, Redis
  `chart.updated` / `series.delayed` / `series.resumed`, price snapshot and throttled channel with stale flag and
  reconnect, `GET /healthz/full`.
- Golden events from two weeks of real Twelve Data EUR/USD and XAU/USD history with an independent rule review;
  `scripts/benchmark.py` (AD-03), `scripts/record_golden.py`, development-only Lightweight Charts page and
  `scripts/dev_chart.py`; engine demo checklist `docs/demo/INCREMENT1_DEMO.md` (task 1.10).
- Migration 0002: accounts, plans, prices, country currencies, founder slots, subscriptions, setups and
  append-only setup revisions, watchlists; plan loader with closed limit keys; `load-plans`, `create-user`
  (Argon2id, development/staging only) (task 2.1).
- Engine scoring: Q and C factors, combined rank from `rule_versions.weights`, counter-trend badge, batch-end
  re-evaluation and template explanations (task 2.2).

### Changed (Day 4)
- `SetupCandidate` carries the primary zone bounds, the broken level and the displacement length;
  `engine/tests/data/synthetic_2000.json` regenerated for these fields only (no rule change).
- `liquidity_levels` kinds may change while a level is active (a kind joins or a superseded one leaves).
- `seed` also loads `config/plans.json`; `normal_spread` values are flagged as placeholders (no bid/ask from
  Twelve Data).

### Added (Day 3, 8 Nov 2026)
- Engine, test-first: liquidity levels (swing, PDH/PDL, PWH/PWL, Asian/London/NY sessions), EQH/EQL with ATR
  tolerance, same-candle sweeps and breakouts; displacement; order blocks (promoted on a same-direction internal
  break within 3 candles); zone lifecycle for OBs and FVGs (touched, 50 %, filled, invalidated, retests, expiry).
- `step()` follows all ten steps of DD 3.4 and returns level changes and setup candidates; `SeriesState` v2
  with a type-checked JSON codec; `build_context`, `run_multi` (close-time merge, ties to the higher timeframe).
- Property tests on the golden file `engine/tests/data/synthetic_2000.json` (step vs run, truncation for every n,
  forming 4H candle through `run_multi`, two-process determinism); recorded-provider event test (FR-DATA-07).

### Added (Day 2, 7 Nov 2026)
- Market-data pipeline (CR-004): candle-provider port, Twelve Data adapter with FREE-plan credit limiter,
  symbol map in `config/instruments.json`, completed-candle rule, calendar-aware gaps and backfill
  (`data_gaps`, `series_status` delayed/ok), 15m/1h from 5m and 4h/1d from 1h on 17:00 New York,
  ingest job every 5 minutes in the worker, synthetic/recorded fakes for all 55 series, `verify-instruments`.
- `make test-db` (throwaway PostgreSQL), `make web-check`, GitHub Actions CI; Windows `MSYS_NO_PATHCONV`.
- Engine rules, test-first: swings, trend, BOS/CHoCH, FVG; `SeriesState` (JSON), `step()`, `run()`;
  no-look-ahead, determinism and step-vs-run property tests.

### Added (Day 1, 5 Nov 2026)
- Repository skeleton in the feature-based layout of ADR-0001 (engine, backend, web, admin-web, deploy, config, docs).
- Docker Compose for proxy, web, admin-web, api, worker, postgres and redis with health checks; Caddyfile; `.env.example`.
- `tradelens_engine` primitives, test-first: candle type, settings and allowed values, settings hash,
  integer ATR and comparisons, combined score, deterministic IDs, New York day/week/session keys.
- Backend: `GET /healthz`, worker heartbeat and health check, `python -m tradelens.cli doctor|seed`.
- Alembic migration 0001 (market data and engine output tables, append-only and guard triggers).
- Config: 11 instruments, 2 trading calendars, rule version r1.0 with 4 presets, plans and prices (CR-003).
- Quality gates: ruff, mypy (strict for the engine), import-linter contracts, architecture test, pre-commit.
- Docs: coding standards, onboarding, module map, ADR-0001 and AD-01..AD-14.
- Review fixes (ecc:python-reviewer): strict HH:MM parsing, validated rule constants, guards on presets and
  liquidity levels, TRUNCATE blocked on append-only tables, rule-version FKs and timeframe checks, seed drift
  detection and clean exit codes, request-ID middleware, Redis client closed after health checks.
