# ADR-0001: Feature-based module structure for the TradeLens repository

- **Status:** Accepted (5 Nov 2026, approved by Punith with adjustments A1–A4)
- **Deciders:** Punith (developer)
- **Related:** SRS v1.3, Software Design Document v1.2 §10, Detailed Design §1 (DD-1..DD-8), §8 (increment plans)

## Context

TradeLens is a modular monolith built solo in 14 days (3 increments: days 1–5, 6–9, 10–14). It has a pure SMC engine, a FastAPI backend (API and worker share one image), two Next.js apps (`web` for tradelens.com and app.tradelens.com, `admin-web` for admin.tradelens.com), PostgreSQL 16, Redis 7 and Docker Compose.

The Day 1 skeleton grouped the backend by technical layer (`api/`, `adapters/`, `ops/`, `worker/`), but the user asked for feature-based modules. We need a layout that:

- keeps business rules testable without infrastructure;
- stops modules reaching into each other's tables;
- lets a new developer find code by feature;
- does not over-engineer a two-week build.

## Decision

### 1. Repository layout

```
tradelens/
├─ engine/src/tradelens_engine/           pure engine: no I/O, no clock, integers only
│  ├─ types.py settings.py arith.py ids.py timekeys.py series.py step.py run.py profiles.py
│  └─ rules/  atr swings structure displacement order_blocks fvg liquidity sweeps zones mtf scoring explain
├─ backend/
│  ├─ alembic.ini   migrations/{env.py, sql/, versions/0001..0003}
│  ├─ src/tradelens/
│  │  ├─ core/          config db redis clock errors security pagination logging deps
│  │  ├─ modules/       accounts billing market_data analysis scanner charts watchlists
│  │  │                 customization alerts notifications realtime monitoring admin
│  │  ├─ integrations/  oanda/ razorpay/ brevo/ redis_publisher cloudflare_access system_clock fakes/
│  │  ├─ app/           main.py (create_app), bootstrap.py, routers.py, middleware.py, exception_handlers.py
│  │  ├─ worker/        main.py scheduler.py heartbeat.py healthcheck.py jobs/
│  │  └─ cli/           doctor seed verify_instruments create_user
│  └─ tests/  unit/ integration/ contract/ architecture/
├─ web/src/        app/ (thin routes)  features/<feature>/  components/{ui,layout}/  lib/
├─ admin-web/src/  same shape
├─ e2e/            Playwright: 4 smoke tests in Release 1
├─ config/         plans.json instruments.json calendars.json rules/ presets/
├─ deploy/         compose (+dev), Caddyfile, Dockerfile.backend, .env.example, postgres-init/, backup/
├─ scripts/        export_openapi, gen_api_types, release
└─ docs/           adr/ architecture/MODULE_MAP.md ONBOARDING.md runbook/ handover/ api/ superpowers/plans/
```

### 2. Backend module shape

A module contains only the files it needs:

```
modules/<name>/
  README.md     purpose, requirement IDs, tables, endpoints, dependencies, key files   (A4)
  router.py     FastAPI routes, kept thin
  service.py    use cases and business rules; must not import FastAPI
  repository.py SQLAlchemy queries
  models.py     ORM tables
  schemas.py    Pydantic v2 request and response models
  errors.py
  public.py     ONLY when another module consumes this one (A1)
  ports.py      ONLY for an external dependency: OANDA, Razorpay, email, clock (A1)
```

### 3. Module ownership

| Module | Owns |
|---|---|
| notifications | email_outbox and in-app notifications |
| realtime | SSE stream and Redis fan-out |
| market_data | instruments, calendars, candles, series_status, data_gaps |
| accounts | users, sessions, email tokens |
| billing | plans, prices, currency, trial, founder slots and claims, subscriptions, payments, refunds, webhook; exposes `Entitlements` |
| customization | profiles |
| analysis | rule versions, presets, series state, events, liquidity, zones, setups and revisions; the only writer of engine output |
| scanner | read-only: scanner and setup detail |
| charts | read-only chart payload |
| watchlists | watchlists |
| alerts | alert rules and deliveries |
| monitoring | health and monitor state |
| admin | audit log and admin API |

Billing stays one module because taking a founder slot and activating a subscription must commit in one transaction. MTF is an engine rule, not a module.

### 4. Dependency rules

- Dependencies point inward: `app`/`worker`/`cli` → `modules` → `core`.
- Only `analysis` imports `tradelens_engine`.
- The engine imports nothing outside itself.
- A module imports another module only through that module's `public.py`.
- Modules never import `integrations`. Integrations implement the modules' `ports.py`.
- Wiring happens only in `app/bootstrap.py` and `worker/main.py`.

Module layers, from top to bottom (a module may import only modules below it):

| Layer | Modules |
|---|---|
| 1 | admin, monitoring |
| 2 | alerts, charts, watchlists |
| 3 | scanner |
| 4 | analysis, customization |
| 5 | billing |
| 6 | accounts, market_data, realtime, notifications |

**Enforcement (A2).**

From Day 1, import-linter contracts in `backend/pyproject.toml`:
- `core-is-leaf`
- `modules-dag`
- `module-hexagon`
- `public-is-leaf`
- `no-integration-leak`
- `no-web-in-service`
- `roots-are-roots`

Also from Day 1:
- `engine-purity` in `engine/pyproject.toml`;
- `backend/tests/architecture/test_module_boundaries.py`, an AST check that cross-module imports go through `public.py` only.

From Increment 2, `eslint-plugin-boundaries` enforces these frontend rules:
- `feature-isolation`
- `app-is-thin`
- `ui-is-leaf`
- `lib-is-leaf`
- `no-cross-app`

### 5. Frontends

- `web` and `admin-web` are independent apps with no shared `packages/` workspace.
- Shared types are generated from the backend OpenAPI file into each app's `lib/api/schema.d.ts`.
- Each feature folder has `components/ hooks/ api.ts types.ts index.ts README.md` (A4) and exports only through `index.ts`.

### 6. Database

| Concern | Location |
|---|---|
| Roles and extensions | `deploy/postgres-init/` |
| Schema, append-only triggers and grants | `backend/migrations/`, central because foreign keys cross modules; one migration per increment (DD-8) |
| Seed data | `config/*.json`, loaded idempotently by `python -m tradelens.cli seed` |

### 7. Naming

**Python**
- Files are snake_case; classes are PascalCase.
- Suffixes: `XService`, `XRepository`, `XPort`.
- ORM classes are singular; tables are plural snake_case.
- Constraints are named `ck_`, `uq_` or `fk_<table>_<col>`; indexes `ix_`; triggers `<table>_guard`.
- Google docstrings that cite FR IDs.

**API**
- Customer routes are `/api/v1/<plural-kebab>`; admin routes `/api/admin/v1/...`; health is `/healthz`.

**TypeScript**
- Components are `PascalCase.tsx`; hooks are `useX.ts`; other files kebab-case.
- Tests are `*.test.ts(x)`, next to the code.

### 8. Documentation and scope rules

- **(A3)** `e2e/` holds exactly four smoke tests in Release 1: `signup_trial`, `checkout`, `scanner_alert` and `admin_refund`.
- **(A4)** Every backend module and frontend feature has a `README.md`.
- `docs/ONBOARDING.md` holds a "where do I find…" table, and `docs/architecture/MODULE_MAP.md` maps modules to their requirements and tables.
- `ecc:update-codemaps` runs at the end of each increment.

## Alternatives considered

- **Layer-based** (`api/`, `services/`, `repositories/`): rejected. A feature's code would be spread across folders, and nothing stops cross-feature table access.
- **Full hexagon in every module** (`domain/`, `application/ports/in|out`, `adapters/`): rejected as too much ceremony for 14 days. Ports are kept only for the 4 external systems.
- **17 modules** (separate catalog, offers and zones): rejected. It splits transactions that must be atomic.
- **Frontend `packages/` workspace:** rejected. The two apps would share about 10 files, which does not justify workspace tooling or the Docker context changes. Revisit above about 15 shared files.
- **Event bus between modules:** deferred. Worker jobs call public services directly.

## Consequences

**Positive**
- Code is found by feature.
- Boundaries are machine-checked from Day 1.
- Vendors can be swapped in one folder.
- Fakes make tests and local development independent of OANDA, Razorpay and SMTP.

**Negative**
- The Day 1 skeleton must be restructured: about 40 files move and the imports change.
- Startup commands change:
  - api: `uvicorn tradelens.app.main:create_app --factory`
  - worker: `python -m tradelens.worker.main`
  - healthcheck: `python -m tradelens.worker.healthcheck`
  - operator commands: `python -m tradelens.cli <cmd>`
- Detailed Design §6.6 (Compose) and §6.8 (Makefile) must use these commands.
- There is a small duplicated UI kit across the two apps.
- Writing a README per module adds a little ongoing work, mitigated by the codemap refresh at each increment's end.
