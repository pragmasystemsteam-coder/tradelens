# TradeLens coding standards

Written for the developer and any future team reviewing this code. The machine-checked parts run in
`make check` (ruff, mypy, import contracts, tests) and in pre-commit.

## Structure (ADR-0001, refines SDD section 10)

- Code is organised **by feature**, not by layer: `backend/src/tradelens/modules/<module>/` with only
  the files the module needs (`router.py`, `service.py`, `repository.py`, `models.py`, `schemas.py`,
  `errors.py`; `public.py` only when another module uses it; `ports.py` only for OANDA, Razorpay, email, clock).
- Dependencies point inward: `app` / `worker` / `cli` → `modules` → `core`. Modules use other modules only
  through `public.py`, in the layer order of ADR-0001 section 4. Only `analysis` imports `tradelens_engine`.
- Routers stay thin; services never import FastAPI; repositories hold all SQL.
- Frontends: `src/app/` holds thin route files; `src/features/<feature>/` holds components, hooks, `api.ts`,
  `types.ts`, `index.ts`; `src/components/ui/` and `src/lib/` are shared leaves. A feature never imports
  another feature's internals.
- Every backend module and frontend feature has a `README.md` (purpose, requirement IDs, tables,
  endpoints, dependencies, key files).

## Python

| Rule | How it is enforced |
| --- | --- |
| PEP 8, line length 100, sorted imports | `ruff check` and `ruff format` (`ruff.toml`) |
| Full type hints on every function | ruff `ANN`; mypy: **strict** for `engine/`, `disallow_untyped_defs` for `backend/` |
| Google-style docstrings on public modules, classes, functions (purpose, Args, Returns, Raises) | ruff `D` (google convention) |
| `snake_case` functions and modules, `PascalCase` classes, `UPPER_CASE` constants | ruff `N` |
| No magic numbers: named constants or settings | ruff `PLR2004`; engine values come from `rule_versions.settings.constants` |
| Specific exceptions only; never bare or blind `except` | ruff `BLE`, `E722` |
| Structured JSON logging (`tradelens.core.logging`), request IDs; never `print` | ruff `T20` |
| Engine: small pure functions, integers only, no I/O, clock or randomness | `engine/tests/test_purity.py`, `engine-purity` contract, mypy strict |
| Module boundaries | import-linter contracts in `backend/pyproject.toml`, `tests/architecture/` |

Domain conventions: prices are integers in the instrument's smallest unit; ATR is stored x1000
(`atr_k`); multipliers are thousandths; compare by cross-multiplying, never by dividing. Every
event carries `origin_time` (where it formed) and `confirm_time` (when it became knowable); nothing
may use a candle that has not closed (no look-ahead).

## TypeScript

- `strict: true`; ESLint (`next/core-web-vitals`, `next/typescript`) and Prettier (print width 100).
- The API client is typed from the backend's OpenAPI file (`lib/api/schema.d.ts`, generated).
- Components `PascalCase.tsx`; hooks `useX.ts`; other files kebab-case; tests `*.test.ts(x)` beside the code.
- Feature-boundary lint rules (eslint-plugin-boundaries) are added in Increment 2.

## Comments

- Explain **why**, not what.
- Every SMC rule function cites its requirement and rule source, e.g.
  `Implements FR-SMC-04 (close-based BOS, CD-15).`
- Note non-obvious decisions: integer prices, `confirm_time` vs `origin_time`, no look-ahead, exact type checks.
- No commented-out code. A `TODO` must carry a requirement or issue ID: `# TODO(FR-ALERT-05): ...`.

## Tests

- pytest. Test names state behaviour: `test_bullish_fvg_requires_strict_gap`.
- Reference requirement IDs in the module docstring or the test name where one applies.
- Arrange, act, assert. Real code over mocks; fakes only at the edges (Redis, OANDA, Razorpay, clock).
- Test-first for engine rules and billing (Detailed Design 7.1). A test that needs PostgreSQL is marked
  `integration` and skips without `TEST_DATABASE_URL`.
- Relaxed in tests only: docstrings, annotations, magic values, pytest style rules PT006/PT011/PT018, and
  `l` as the OHLC low (`ruff.toml`).

## Repository hygiene

- Conventional Commits when commits are requested: `feat:`, `fix:`, `test:`, `docs:`, `refactor:`, `chore:`.
- `README.md` has setup and run steps; `CHANGELOG.md` records each increment; decisions go in `docs/adr/`.
- `.editorconfig` for whitespace; `pre-commit install` runs ruff, mypy, import contracts, ESLint and Prettier.
- Secrets only in `deploy/.env` (never committed); `make doctor` refuses placeholders.
