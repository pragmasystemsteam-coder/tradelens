# Day 2–3: Data pipeline (Twelve Data, CR-004) and engine structure rules — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the Day 1 leftovers, ingest complete candles for all 55 series (Twelve Data live subset + recorded/fake data for the rest), and build the engine's swings, trend, BOS/CHoCH and FVG rules with `step()`/`run()`.

**Architecture:** `market_data` gets a candle-provider port (`ports.py`) and pure helpers (completion rule, calendar, aggregation, gaps); `integrations/twelvedata` and `integrations/fakes` implement the port; the worker runs an ingest job every 5 minutes. The engine gets `rules/{swings,structure,fvg}.py`, `series.py` (state), `step.py`, `run.py` per ADR-0001.

**Tech Stack:** Python 3.12, httpx, SQLAlchemy 2 Core, PostgreSQL 16, pytest; GitHub Actions; Next.js 15 (typecheck/lint/build only).

**Spec:** Detailed Design §2.4, §3.1–3.4, §6, §7.2–7.3, §8.1 (tasks 1.3–1.9); PROJECT_HANDOFF.md §13 (CR-004); ADR-0001.

## Global Constraints

- Engine: no I/O, clock, randomness or floats; integers only; every event has `origin_time` and `confirm_time`.
- Only complete candles: a bar is complete only when `open_time + timeframe <= now`; the forming bar is never stored.
- 4H and 1D are built from 1H on the 17:00 America/New_York boundary (DST-aware via `ZoneInfo`).
- Twelve Data FREE plan: ≤ 8 credits/minute, ≤ 800/day (1 credit = 1 symbol per request).
- Tests never call Twelve Data; they use recorded-format JSON. The key lives only in `deploy/.env`; never printed, logged or committed.
- Modules never import `integrations`; wiring only in `worker/main.py`, `cli`, `integrations/providers.py`.

## Decisions taken here (record in DAILY_LOG)

- **D2-1 Budget:** a full trading day of 5m+15m+1h for 2 instruments costs ~816 credits (> 800). So live polling fetches **5m only**; live 15m and 1h are aggregated from 5m (UTC-aligned buckets), 4h/1d from 1h (17:00 NY). History for 5m, 15m, 1h is fetched once per series (`outputsize` = `BACKFILL_MIN_CANDLES`, max 5000) and cached; ingestion always resumes from the last stored candle. Live load ≈ 576 credits/day.
- **D2-2 Spread:** Twelve Data time series are mid only, so `bid_* = ask_* = mid` (spread 0, spread factor scores 0 in development, §13).
- **D2-3 Aggregate completeness:** a bucket is built only when every calendar-expected constituent bar is stored and the bucket has closed; otherwise nothing is built (the gap belongs to the source series).
- **D2-4 Engine layout:** ADR-0001 names (`rules/swings.py`, `rules/structure.py`, `rules/fvg.py`, `series.py`, `step.py`, `run.py`) over the DD's `structure/` folder.

## Review Focus

1. Twelve Data returns the forming bar → it must be dropped; test `test_forming_bar_is_dropped`.
2. A "run out of API credits" body with HTTP 200 → `RateLimitedError`, never parsed as candles; test `test_credit_error_body_raises`.
3. Gold daily break (17:00–18:00 NY) and Sunday open → not gaps; the 17:00–21:00 metal 4H bucket has 3 constituents; tests `test_metal_break_not_expected`, `test_metal_4h_bucket_built_from_three_bars`.
4. DST weeks (March/November) → daily bucket opens at 17:00 local on both sides; test `test_daily_bucket_17ny_both_dst`.
5. Price strings with more decimals than `price_scale` → error, no silent rounding; test `test_parse_price_rejects_extra_digits`.

---

## DAY 2

### Task A: Day 1 leftovers
**Files:** `Makefile`, `.github/workflows/ci.yml`, Detailed Design §6.6/§6.8 (Claude Doc).
- [x] Makefile: on Windows `export MSYS_NO_PATHCONV := 1`; `test-db` (throwaway `postgres:16-alpine` on `127.0.0.1:55432` with `deploy/postgres-init`, wait for `pg_isready`, `pytest -m integration` with `TEST_DATABASE_URL`, always remove); `web-check`; `verify-instruments`.
- [x] `make test-db` → all integration tests PASS.
- [x] `npm install` + typecheck, lint, build for `web/` and `admin-web/`; commit lock files.
- [x] CI: `backend` (ruff, format, mypy, lint-imports, pytest incl. DB tests on a `postgres:16-alpine` service), `frontend` (matrix: `npm ci`, typecheck, lint, build), `docker` (`docker compose config` with `.env.example`, image builds). Placeholder secrets only.
- [x] Detailed Design §6.6/§6.8: new start commands (`uvicorn tradelens.app.main:create_app --factory`, `python -m tradelens.worker.main`, `python -m tradelens.worker.healthcheck`) and the `test-db` target.

### Task B: Provider port, price parsing, completion rule
**Files:** `market_data/ports.py`, `market_data/candles.py`; `tests/unit/modules/market_data/test_candles.py`.
**Produces:** `RawBar(open_time, o, h, l, c)`; `CandleProvider` Protocol `fetch(instrument, timeframe, *, count, start=None, end=None) -> list[RawBar]`; `ProviderError`, `RateLimitedError`, `BudgetExhaustedError`; `parse_price(text, price_scale) -> int`; `complete_bars(bars, timeframe, now)`; `StoredCandle`; `to_stored(bar, instrument, timeframe, source)`.
- [x] Tests: `test_parse_price_string_to_int`, `test_parse_price_rejects_extra_digits`, `test_parse_price_rejects_garbage`, `test_forming_bar_is_dropped`, `test_bar_complete_exactly_at_close`, `test_stored_candle_mid_for_bid_and_ask`, `test_bars_sorted_and_deduplicated`. FAIL → implement → PASS.

### Task C: Calendar, gaps, aggregation
**Files:** `market_data/calendar.py`, `market_data/aggregate.py`; tests `test_calendar.py`, `test_aggregate.py`.
**Produces:** `Calendar.from_row`, `is_open`, `expected_open_times(cal, tf, start, end)`, `find_gaps(cal, tf, stored)`, `bucket_open(tf, t)`, `aggregate(cal, source_tf, target_tf, bars, now)`.
- [x] Tests: `test_sunday_open_expected`, `test_saturday_not_expected`, `test_metal_break_not_expected`, `test_gap_only_if_later_candle_exists`, `test_daily_alignment_17_ny`, `test_daily_bucket_17ny_both_dst`, `test_4h_buckets_17_21_01_05_09_13_ny`, `test_aggregate_ohlc`, `test_incomplete_bucket_not_built`, `test_metal_4h_bucket_built_from_three_bars`, `test_15m_from_5m_utc_aligned`. FAIL → implement → PASS.

### Task D: Twelve Data adapter, rate limiter, symbol map, fakes
**Files:** `integrations/{providers}.py`, `integrations/twelvedata/{client,rate_limiter}.py`, `integrations/fakes/{synthetic,recorded}.py`; `config/instruments.json` (`provider_symbols.twelvedata`); `market_data/service.py`; fixtures `tests/fixtures/twelvedata/*.json`.
**Produces:** `CreditLimiter(per_minute=8, per_day=800, clock, sleep).acquire(credits=1)`; `TwelveDataProvider(api_key, symbols, price_scales, limiter, http)` (`/time_series`, `interval` 5min/15min/1h, `timezone=UTC`, `order=ASC`, `dp=price_scale`; key redacted everywhere); `SyntheticProvider`; `RecordedProvider`; `RoutingProvider(live, fallback, live_instruments)`; `build_candle_provider(env, instruments)` from `MARKET_DATA_PROVIDER` and `TWELVEDATA_LIVE_INSTRUMENTS` (default `EUR_USD,XAU_USD`).
- [x] Tests: `test_time_series_recorded_response_parsed`, `test_credit_error_body_raises`, `test_http_error_raises_provider_error_without_key`, `test_symbol_map_complete_and_unique`, `test_limiter_waits_after_8_credits_in_a_minute`, `test_limiter_raises_after_800_a_day_and_resets_at_utc_midnight`, `test_synthetic_deterministic_and_valid_ohlc`, `test_routing_live_subset`, `test_factory_fake_without_key`, `test_factory_twelvedata_requires_key`. FAIL → implement → PASS.

### Task E: Repository, ingest service, gaps/backfill, worker job
**Files:** `market_data/repository.py`, `market_data/ingest.py`, `worker/scheduler.py`, `worker/jobs/ingest.py`, `worker/main.py`; tests unit `test_ingest.py`, integration `tests/integration/market_data/test_ingest_db.py`.
**Produces:** `IngestService.run_once(store, now) -> IngestReport`: history once (5m/15m/1h), live 5m from the last stored candle, gaps → `data_gaps` + status `delayed`/`backfilling` → `ok`, derive 15m/1h from 5m and 4h/1d from 1h; `next_run_at(now, period_s=300, offset_s)`.
- [x] Tests: `test_history_fetched_once_then_incremental`, `test_forming_bar_never_stored`, `test_gap_delays_backfills_resumes`, `test_derived_series_built_after_source`, `test_budget_exhausted_marks_delayed_not_crash`, `test_next_run_on_5_minute_boundary_plus_offset`, `test_all_55_series_ok_with_fake_provider` (DB). FAIL → implement → PASS.

### Task F: verify-instruments CLI
**Files:** `cli/verify_instruments.py`, `cli/__main__.py`; test `tests/unit/cli/test_verify_instruments.py`.
- [x] Tests: `test_verify_reports_missing_symbol`, `test_verify_reports_unknown_symbol_from_recorded_search`, `test_verify_ok_with_recorded_search`.
- [x] Optional live check only if `TWELVEDATA_API_KEY` is set: one EUR/USD 5m call; print bar times and count only.

### Day 2 close
- [x] `make check`, `make test-db` green; ecc:python-reviewer, HIGH fixed; DAILY_LOG; `reports/TradeLens_Day2_Report.pdf`.

---

## DAY 2, PART 2 (engine, test-first; DD 3.4, 7.2, 7.3)

### Task G: Swings — `rules/swings.py`
**Produces:** `Swing(kind, price, bar, origin_time, confirm_time)`; `confirm_swing(window, last_bar, left, right) -> list[Swing]`: candidate `k = t − R` is a high when `H[k] > max(H[k−L..k−1])` and `H[k] >= max(H[k+1..t])`; mirror lows.
- [x] Tests: `test_3_3_pivot_confirmed_at_close_of_i_plus_3`, `test_higher_high_in_right_window_rejects`, `test_equal_high_on_right_confirms`, `test_equal_high_on_left_rejects`, `test_plateau_gives_first_swing`, `test_mirror_low`, `test_not_enough_bars_returns_nothing`, `test_pivot_lengths_internal_3_htf_5_external_10`.

### Task H: Trend, BOS, CHoCH — `rules/structure.py`
**Produces:** `Structure` (trend, last 30 highs/lows, unbroken stacks, protected high/low); `add_swing(st, swing)`; `detect_breaks(st, candle, atr_k, buf_m) -> (Structure, list[Break])`.
- [x] Tests: `test_hh_hl_turns_bull`, `test_one_higher_high_stays_neutral`, `test_lh_ll_turns_bear`, `test_equal_values_keep_neutral`, `test_close_above_unbroken_high_in_bull_is_bos`, `test_wick_is_not_bos`, `test_close_equal_to_level_is_not_bos`, `test_one_bos_per_level`, `test_older_unbroken_level_kept`, `test_neutral_break_emits_nothing`, `test_choch_first_close_beyond_protected`, `test_close_beyond_non_protected_swing_no_choch`, `test_choch_never_from_neutral`, `test_mirror_bear_bos`.

### Task I: FVG — `rules/fvg.py`
**Produces:** `Fvg(direction, low, high, origin_time, confirm_time, bar)`; `detect_fvg(a, b, c, bar, atr_k, fvg_min_m) -> Fvg | None`.
- [x] Tests: `test_bullish_fvg_requires_strict_gap`, `test_equal_values_no_gap`, `test_overlap_of_one_unit_no_gap`, `test_bearish_fvg`, `test_min_size_filters_with_atr`, `test_min_size_without_atr_not_created`, `test_min_size_zero_off`.

### Task J: SeriesState, step(), run()
**Files:** `series.py`, `events.py`, `step.py`, `run.py`; tests `test_step_run.py`, `test_properties.py`.
**Produces:** `SeriesState` with `to_json()/from_json()`; `step(state, candle, cfg, *, instrument, timeframe, rule_version) -> (SeriesState, StepOutput)` (order check → ATR → swings → breaks → FVG); `run(candles, cfg, *, instrument, timeframe, rule_version) -> EngineResult`; `OutOfOrderCandle`.
- [x] Tests: `test_out_of_order_raises`, `test_events_carry_ids_and_settings_hash`, `test_step_vs_run_parity_with_json_round_trip`, `test_truncation_no_look_ahead`, `test_determinism_two_processes`, `test_worked_example_bull_trend_then_bos`.

### Day 2 close (engine part)
- [x] `make check`, `make test-db` green; ecc:python-reviewer, HIGH fixed; DAILY_LOG; `reports/TradeLens_Day2_Report.pdf` (Day 2 and 3 work combined into one Day 2 report at the user's request).
