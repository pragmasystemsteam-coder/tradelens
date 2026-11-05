# TradeLens Day 1 (Increment 1 start) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repository skeleton with Compose and Makefile, the `tradelens_engine` primitives (types, settings, integer arithmetic, IDs, time keys) built test-first, and Alembic migration 0001 plus seed for the Increment-1 schema.

**Architecture:** Modular monolith in the feature-based layout of ADR-0001 (`docs/adr/0001-feature-based-module-structure.md`; restructured mid-day 5 Nov 2026, paths below updated). `engine/src/tradelens_engine` is pure (no I/O, clock, randomness or floats). `backend/src/tradelens/` holds `core/`, `modules/<feature>/`, and the roots `app/`, `worker/`, `cli/`; Alembic in `backend/migrations/`. Business values live in `config/*.json`; secrets only in `deploy/.env`.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, psycopg 3, redis-py, pytest; Next.js + TypeScript stubs; PostgreSQL 16; Redis 7; Docker Compose; Caddy.

**Spec:** TradeLens Detailed Design (https://claude.ai/artifact/7zsmg9EJXJp3cbJwadGMtk) sections 2.1, 2.4, 2.5, 3.1–3.3, 3.8, 4.8, 6.1–6.8, 8.1 tasks 1.1–1.3; SDD §10 layout; `PROJECT_HANDOFF.md` §12.

## Global Constraints

- Python 3.12 (`py -3.12`), venv at `tradelens/.venv` (git-ignored; OneDrive folder).
- `tradelens_engine` imports nothing from `backend`; no I/O, wall clock, randomness or floats.
- Prices are integers in smallest units; ATR × 1000 (`atr_k`); multipliers in thousandths; `combined = (600*Q + 400*C + 500) // 1000`.
- Times are UTC `datetime`s with tzinfo; the trading day starts 17:00 America/New_York.
- IDs: `sha256("|".join(fields)).hexdigest()[:32]`, times `YYYY-MM-DDTHH:MM:SSZ`, null → `""`.
- `settings_hash = sha256(json.dumps({"rule_version", "settings", "constants"}, sort_keys=True, separators=(',',':')))` (64 hex).
- One migration per increment; append-only enforced by triggers.
- Docker is not installed: anything needing PostgreSQL/Redis is an `integration` test that skips without `TEST_DATABASE_URL`.
- No commits unless the user asks (Commit steps are skipped today).

## Review Focus

1. Naive (tz-less) datetimes reaching IDs or time keys would silently hash local time → `make_id` and `ny_day_key` raise `ValueError` on naive input (Task 2 tests).
2. Booleans or floats in settings (`True` is an `int`) would change the hash and break integer maths → `Settings.from_json` rejects them (Task 2 tests).
3. DST transition weeks: 17:00 New York must still roll the day in both EST and EDT (`test_day_key_17ny_both_dst`).
4. Seeding twice must not duplicate rows or activate a second rule version → `ON CONFLICT DO NOTHING`, activate only when none active (Task 3 integration test).
5. Instrument `pip_scale > price_scale` typos in JSON → config loader rejects (Task 3 unit test).

---

### Task 1: Repository skeleton, Compose, Makefile, `/healthz`

**Files:**
- Create: `.gitignore`, `README.md`, `Makefile`, `pytest.ini`
- Create: `backend/pyproject.toml`, `backend/src/tradelens/core/{config,db,redis,logging}.py`, `backend/src/tradelens/modules/monitoring/{service,router}.py`, `backend/src/tradelens/app/{main,bootstrap,routers}.py`, `backend/src/tradelens/worker/{main,heartbeat,healthcheck}.py`, `backend/src/tradelens/cli/{__main__,doctor}.py`
- Test: `backend/tests/unit/modules/monitoring/test_health.py`, `backend/tests/unit/worker/test_worker_{healthcheck,main}.py`, `backend/tests/unit/cli/test_doctor.py`, `backend/tests/unit/core/test_{config,logging}.py`, `backend/tests/architecture/test_module_boundaries.py`
- Create: `deploy/{docker-compose.yml,Caddyfile,.env.example,Dockerfile.backend}`, `deploy/postgres-init/01-roles.sh`
- Create: `web/` and `admin-web/` Next.js stubs (`package.json`, `tsconfig.json` with `@/*` → `./src/*`, `next.config.mjs`, `eslint.config.mjs`, `.prettierrc.json`, `src/app/{layout,page}.tsx`, `src/app/healthz/route.ts`, `Dockerfile`)

**Interfaces:**
- Produces: `tradelens.app.main:create_app` (run with `--factory`); `tradelens.modules.monitoring.service.HealthChecks` (`db_ok() -> bool`, `redis_ok() -> bool`, each bounded to 2 s) via dependency `router.get_checks`, wired in `app/bootstrap.py`; `tradelens.worker.healthcheck.check(redis, now: float, ttl: int) -> int`; Redis key `worker:heartbeat` (epoch seconds, written every `HEARTBEAT_INTERVAL_SECONDS`=5 with TTL `HEARTBEAT_TTL_SECONDS`=15); `tradelens.cli.doctor.check_env(env: Mapping[str, str]) -> list[str]` (errors), run as `python -m tradelens.cli doctor deploy/.env`.

- [ ] Write `test_healthz_ok` (fake checks both up → 200 `{"status": "ok"}`), `test_healthz_503_when_db_down` (→ 503 `{"status": "error", "db": false, "redis": true}`), `test_worker_healthcheck_exit_0_with_heartbeat` (heartbeat 3 s old, ttl 15 → 0), `test_worker_healthcheck_exit_1_without_heartbeat` (missing or 20 s old → 1), `test_doctor_flags_placeholder_and_cf_access` (placeholder secret and `APP_ENV=production` + `CF_ACCESS_ENABLED=false` → errors; filled env → `[]`).
- [ ] Run `make test-api`; expect FAIL (imports missing).
- [ ] Implement the files; Compose has the 7 services of §6.6 (proxy, web, admin-web, api, worker, postgres, redis) with health checks, `depends_on: service_healthy`, networks `edge` / `backend` (internal) / `egress`, memory and CPU limits, log rotation 20 MB × 7, volumes. The backup service arrives with the backup scripts (task 3.11).
- [ ] Run `make test-api`; expect PASS. `docker compose -f deploy/docker-compose.yml config` once Docker is installed.

### Task 2: Engine primitives (test-first)

**Files:**
- Create: `engine/pyproject.toml`, `engine/src/tradelens_engine/{__init__,types,settings,arith,timekeys,ids}.py`
- Test: `engine/tests/{test_arith,test_settings,test_ids,test_timekeys,test_types,test_purity}.py`

**Interfaces:**
- `types`: `Timeframe = Literal['5m','15m','1h','4h','1d']`, `Dir`, `Side`, `TIMEFRAMES`, `TIMEFRAME_MINUTES`; frozen-slots `Candle(open_time, close_time, o, h, l, c, bid_c, ask_c)` validating UTC, `close > open`, `h >= max(o, c, l)`, `l <= min(o, c, h)`, `ask_c >= bid_c`, ints only; `Candle.of(open_time, tf, o, h, l, c, bid_c, ask_c)` sets `close_time`.
- `settings`: `Settings` frozen dataclass (8 user fields + `constants: dict`), `Settings.from_json(obj: {"user": …, "constants": …}) -> Settings`, `.to_json() -> dict`, `.hash(rule_version) -> str`, `.internal_pivot_for(tf) -> int`; `ALLOWED_VALUES`; `SettingsError(ValueError)`; `settings_hash(rule_version, user, constants) -> str`.
- `arith`: `ge_atr(x, m, atr_k) -> bool`, `le_atr(x, m, atr_k) -> bool`, `body_ratio_ok(body, rng, permille) -> bool`, `combined_score(q, c, q_permille=600, c_permille=400) -> int`, `AtrState(prev_close, tr_count, tr_sum, atr_k)`, `atr_update(state, candle, period=14) -> AtrState` (refines the design's tuple return; same fields).
- `timekeys`: `ny_day_key(dt) -> date`, `ny_week_key(dt) -> str` (`"2026-W45"`), `sessions_of(open_time, sessions=DEFAULT_SESSIONS) -> tuple[str, ...]` (ordered asian, london, new_york).
- `ids`: `make_id(*fields) -> str`, `event_id(...)`, `zone_id(...)`, `level_id(...)`, `setup_id(...)` with the field orders of §3.8.

- [ ] Write tests: `test_atr_seed_at_14` (14 candles with tr=1 → `atr_k` None after 13, 1000 after 14), `test_atr_half_up` (next tr=0 → 929, not 928), `test_ge_atr_no_atr_false` (atr_k None/0 → False), `test_ge_atr_boundary` (x=15, m=1500, atr_k=10000 → True; x=14 → False), `test_combined_half_up` (Q=60,C=60 → 60; Q=59,C=60 → 60; Q=1,C=0 → 1), `test_settings_rejects_unlisted_value` (external_pivot 9), `test_settings_rejects_bool_float_unknown_missing`, `test_internal_pivot_default_by_tf` (None → 3, 5 on 4h/1d), `test_hash_stable_across_key_order`, `test_hash_changes_with_rule_version`, `test_event_id_field_order` (equals sha256 of the joined string; swapping two fields changes it), `test_make_id_rejects_naive_datetime`, `test_day_key_17ny_both_dst` (16:59 and 17:00 NY in January and July), `test_week_key_sunday_open_is_next_week`, `test_london_ny_overlap_two_sessions` (09:00 NY → london + new_york; 20:00 → asian; 02:59 → asian; 03:00 → london; 17:00 → none), `test_candle_rejects_float_and_bad_hl`, `test_engine_has_no_forbidden_imports` (AST scan: no `random`, `time`, `os`, `socket`, `httpx`, `requests`, `sqlalchemy`, `api`/`worker`/`adapters`, no `float` calls).
- [ ] Run `make test-engine`; expect FAIL.
- [ ] Implement per §3.3, §3.8 and §3.4 "Days, weeks and sessions" (dependency `tzdata` so zoneinfo works on Windows).
- [ ] Run `make test-engine`; expect PASS.

### Task 3: Migration 0001 and seed

**Files:**
- Create: `backend/alembic.ini`, `backend/migrations/{env.py,script.py.mako}`, `backend/migrations/versions/0001_market_engine.py`
- Create: `config/{instruments,calendars,plans}.json`, `config/rules/r1.0.json`
- Create: `backend/src/tradelens/modules/market_data/{service,repository,public}.py`, `backend/src/tradelens/modules/analysis/{service,repository,public}.py`, `backend/src/tradelens/cli/seed.py`
- Test: `backend/tests/unit/cli/test_seed_rows.py`, `backend/tests/integration/migrations/test_{migration_sql,db_integration}.py`

**Interfaces:**
- Consumes: `tradelens_engine.Settings`, `settings_hash`.
- Produces: tables of §2.4 and §2.5 except `setups` / `setup_revisions` (I2); functions `forbid_change`, `rule_versions_guard`, `zones_guard`; `tradelens.cli.seed.load_seed_rows(config_dir: Path) -> SeedRows`; `tradelens.cli.seed.seed(conn: sqlalchemy.Connection, config_dir: Path) -> None` (calls `market_data.public` and `analysis.public`); `make migrate`, `make migrate-sql`, `make seed`.

- [ ] Write `test_seed_counts` (unit, from config: 11 instruments, 2 calendars, 55 series_status, 1 rule version, 4 presets; Default preset hash == rule version hash), `test_instruments_pip_le_price_scale`, `test_presets_valid_settings`, `test_migration_offline_sql_has_tables_and_triggers` (`alembic upgrade head --sql` output contains every I1 table and the guard triggers, and no `setups`); integration (skipped without DB): `test_market_events_append_only`, `test_zone_transitions_append_only`, `test_zones_boundary_immutable_state_updatable`, `test_rule_version_immutable`, `test_seed_idempotent`.
- [ ] Run `make test-api`; expect FAIL.
- [ ] Implement the migration (raw SQL via `op.execute`, downgrade drops), config JSON (§6.2–6.5 values) and seed (`ON CONFLICT DO NOTHING`; activate r1.0 only when no version is active). `plans.json` is written now; its tables and seeding come with migration 0002 (DD-8, task 2.1).
- [ ] Run `make test`; expect PASS, with integration tests reported as skipped.
