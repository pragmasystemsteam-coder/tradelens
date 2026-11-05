# Onboarding: where do I find…

Start with `README.md` (setup), then `docs/adr/0001-feature-based-module-structure.md` (layout and rules)
and `docs/CODING_STANDARDS.md`. Requirements: SRS v1.3; design: Software Design Document and the
Detailed Design (Claude Docs, links in `PROJECT_HANDOFF.md`).

| I want to… | Look in |
| --- | --- |
| Change an SMC rule (swings, BOS, FVG, ATR…) | `engine/src/tradelens_engine/` and its tests in `engine/tests/` |
| See allowed settings, presets, the settings hash | `engine/src/tradelens_engine/settings.py`, `config/rules/r1.0.json` |
| Add or change an instrument or trading calendar | `config/instruments.json`, `config/calendars.json` (validated by `modules/market_data/service.py`) |
| Change plans, prices or limits | `config/plans.json` (seeded with migration 0002) |
| Add an API endpoint | `backend/src/tradelens/modules/<module>/router.py`, registered in `app/routers.py` |
| Wire a real implementation to a module | `backend/src/tradelens/app/bootstrap.py` (API), `worker/main.py` (worker) |
| Change the database schema | a new file in `backend/migrations/versions/` (one per increment) |
| Read or change configuration keys | `deploy/.env.example`, `backend/src/tradelens/core/config.py`, `cli/doctor.py` |
| Run operator commands | `python -m tradelens.cli doctor deploy/.env`, `python -m tradelens.cli seed config` |
| Check health | `GET /healthz` (`modules/monitoring/`), worker: `python -m tradelens.worker.healthcheck` |
| Change containers, routing, TLS | `deploy/docker-compose.yml`, `deploy/Caddyfile`, `deploy/Dockerfile.backend` |
| See which module owns a table or requirement | `docs/architecture/MODULE_MAP.md` |
| Understand a past decision | `docs/adr/` |
| See what was done each day | `docs/DAILY_LOG.md`, `CHANGELOG.md`, `docs/superpowers/plans/` |
| Run all checks | `make check` (Windows: `mingw32-make check`) |
