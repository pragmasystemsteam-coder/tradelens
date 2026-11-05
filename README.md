# TradeLens

Forex and commodities Smart Money Concepts scanner (Release 1). Deterministic rules only, no AI.
Layout and rules: [ADR-0001](docs/adr/0001-feature-based-module-structure.md). New here? Read
[docs/ONBOARDING.md](docs/ONBOARDING.md) and [docs/CODING_STANDARDS.md](docs/CODING_STANDARDS.md).

| Folder | Contents |
| --- | --- |
| `engine/src/tradelens_engine/` | Pure, integer-only SMC engine; tests in `engine/tests/` |
| `backend/src/tradelens/core/` | Config, database, Redis, logging |
| `backend/src/tradelens/modules/` | Feature modules (`monitoring`, `market_data`, `analysis` so far) |
| `backend/src/tradelens/app/` | FastAPI factory (`create_app`), wiring, router list |
| `backend/src/tradelens/worker/` | Worker entry, heartbeat, health check |
| `backend/src/tradelens/cli/` | Operator commands: `doctor`, `seed` |
| `backend/migrations/` | Alembic migrations (one per increment) |
| `backend/tests/` | `unit/`, `integration/`, `architecture/` |
| `config/` | Instruments, calendars, plans, rule versions (business values, NFR-18) |
| `web/`, `admin-web/` | Next.js customer and admin apps (`src/app`, later `src/features`) |
| `deploy/` | Docker Compose, Caddyfile, `.env.example`, Dockerfiles, Postgres init |
| `docs/` | ADRs, architecture map, onboarding, standards, daily log, plans |

## Local development (no Docker needed)

```bash
make install      # Python 3.12 venv in .venv; engine + backend in editable mode with dev tools
make test         # import contracts + every test; DB tests skip unless TEST_DATABASE_URL is set
make check        # ruff + mypy + import contracts + tests (run before every commit)
make migrate-sql  # print the migration SQL without a database
```

### Windows

GNU `make` is not installed by default; `mingw32-make` (MinGW) runs the same Makefile:
`mingw32-make install`, `mingw32-make test`, `mingw32-make check`.

Without any make: `py -3.12 -m venv .venv`, then
`.venv\Scripts\python -m pip install -e engine[dev] -e backend[dev]`, `.venv\Scripts\lint-imports --config backend/pyproject.toml`
and `.venv\Scripts\python -m pytest`.

## Running the stack

Needs Docker Desktop (WSL2 backend on Windows) or Docker Engine with Compose v2.

```bash
cp deploy/.env.example deploy/.env   # fill every value; make doctor checks it
make init                            # doctor, build, migrate, seed, start all services
make health
```

Start commands: API `uvicorn tradelens.app.main:create_app --factory`; worker
`python -m tradelens.worker.main`; operator `python -m tradelens.cli <doctor|seed>`.

Plans: `docs/superpowers/plans/`. Progress: `docs/DAILY_LOG.md`. Changes: `CHANGELOG.md`.
