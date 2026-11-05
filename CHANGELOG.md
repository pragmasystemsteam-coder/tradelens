# Changelog

All notable changes to TradeLens. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow the increments (0.1 = Increment 1, 0.2 = Increment 2, 1.0 = Release 1 handover).

## [Unreleased]

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
