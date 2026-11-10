# Increment 1 engine demo (Detailed Design 7.8, "Day 5" checklist)

Run on the development PC (Windows, Git Bash, Docker Desktop running). Make is not installed,
so each `make` recipe is given as the command it runs. Run from the `tradelens` folder.
Time needed: about 20 minutes (plus 2 minutes of warm-up after `up`).

Data source (CR-004): Twelve Data FREE plan. Only EUR/USD and XAU/USD 5m are live; the other
9 instruments run on the synthetic provider. 15m/1H are built from 5m and 4H/1D from 1H on the
17:00 New York close. There is no live price stream on this plan: the price is the newest 5m close.

## 0. Before the call

```bash
.venv/Scripts/python.exe -m tradelens.cli doctor deploy/.env
```

Expect no errors. Never show `deploy/.env` on screen (it holds the Twelve Data key).

## 1. Automated tests (rule cases, step-vs-run, truncation, higher timeframe, golden)

```bash
.venv/Scripts/python.exe -m pytest -q
```

Expect all passed (DB tests skipped here). Then the database tests in a throwaway PostgreSQL:

```bash
MSYS_NO_PATHCONV=1 .venv/Scripts/python.exe scripts/test_db.py
```

Show: `test_golden_events` (real Twelve Data history), `test_close_batch_highest_tf_first`,
`test_incomplete_candle_at_sunday_open_and_dst_week_marks_delayed_never_stepped`,
`test_events_and_state_one_transaction`, `test_restart_continues_same_events`.

## 2. Engine on real data: the dev chart (no database needed)

```bash
.venv/Scripts/python.exe scripts/dev_chart.py
```

Open `docs/demo/dev_chart_golden.html` in Chrome. It holds two weeks of real EUR/USD and XAU/USD
history (26 Oct - 6 Nov 2026, includes the US clock change on 1 Nov) with the engine output.

- Pick **EUR_USD 1h**, then **XAU_USD 4h** (DD 7.8: "events for EUR/USD 1H and XAU/USD 4H").
- Point at a BOS: the label sits on the candle whose close broke the swing; the dashed line ends there.
- Point at an order block (solid box) and an FVG (dotted box); toggle Zones / Liquidity / Swings.
- Compare with the client's 3 annotated charts (ask them to share the dates and pairs beforehand).

## 3. Full stack with the live pipeline

```bash
docker compose -f deploy/docker-compose.yml --env-file deploy/.env build
docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d postgres redis
MSYS_NO_PATHCONV=1 docker compose -f deploy/docker-compose.yml --env-file deploy/.env run --rm --no-deps -e DATABASE_MIGRATION_URL api python -m alembic -c alembic.ini upgrade head
MSYS_NO_PATHCONV=1 docker compose -f deploy/docker-compose.yml --env-file deploy/.env run --rm --no-deps -e DATABASE_MIGRATION_URL api python -m tradelens.cli seed /app/config
docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d
docker compose -f deploy/docker-compose.yml --env-file deploy/.env ps
```

Expect every container `healthy` (worker within 60 s).

### 3a. 55 series filling and data health

```bash
docker compose -f deploy/docker-compose.yml --env-file deploy/.env exec postgres psql -U tradelens_owner -d tradelens -c "SELECT instrument, timeframe, status, last_candle_time FROM series_status ORDER BY 1, 2"
docker compose -f deploy/docker-compose.yml --env-file deploy/.env exec postgres psql -U tradelens_owner -d tradelens -c "SELECT instrument, timeframe, count(*) FROM candles GROUP BY 1, 2 ORDER BY 1, 2"
```

Expect 55 rows `ok`. 5m, 15m and 1H hold 2,500 candles each, and 4H/1D hold what 2,500 1H candles
give (about 600 and 100). If the database user or name differs, use `POSTGRES_USER` and
`POSTGRES_DB` from `deploy/.env`.

### 3b. A live close is stepped within 10 seconds

```bash
docker compose -f deploy/docker-compose.yml --env-file deploy/.env logs -f worker
```

Wait for the next 5-minute boundary. The `close pass done` line shows `seconds` (expect under 2 on
this PC), `stepped` (11) and `steps`.

### 3c. Health

```bash
curl -s http://localhost/healthz
curl -s http://localhost/healthz/full
```

`/healthz/full` lists `worker`, `series` and `prices`. Then stop the worker and repeat. Within
15 s `worker` turns false and the status is 503, while `/healthz` stays 200 (a dead worker never
restarts the API):

```bash
docker compose -f deploy/docker-compose.yml --env-file deploy/.env stop worker
curl -s -o /dev/null -w "%{http_code}\n" http://localhost/healthz/full
docker compose -f deploy/docker-compose.yml --env-file deploy/.env start worker
```

(Use the API's published port or Caddy host if `localhost` is not routed on this PC.)

### 3d. Recovery

```bash
docker compose -f deploy/docker-compose.yml --env-file deploy/.env kill worker
docker compose -f deploy/docker-compose.yml --env-file deploy/.env ps
```

The worker restarts on its own (`restart: unless-stopped`), loads `series_state` and continues
without re-stepping old candles. `test_restart_continues_same_events` proves the result is identical.

### 3e. Live messages (optional)

```bash
docker compose -f deploy/docker-compose.yml --env-file deploy/.env exec redis redis-cli -a "$REDIS_PASSWORD" SUBSCRIBE updates:EUR_USD data prices:EUR_USD
```

`chart.updated` arrives after each close and `price` every few seconds (newest 5m close).

## 4. Gap handling (simulated)

Real gaps cannot be forced on demand. Show `test_gap_delays_backfills_resumes`: a missing 5m
candle marks the instrument **delayed** (`series.delayed` on the `data` channel). The backfill
fetches it and the series **resumes**, then the late candle is stepped in order, so the events
equal a run without the gap. The gold daily break (17:00-18:00 New York) is not a gap
(`test_metal_break_not_expected`).

## 5. Benchmark (AD-03)

```bash
.venv/Scripts/python.exe scripts/benchmark.py
MSYS_NO_PATHCONV=1 .venv/Scripts/python.exe scripts/benchmark.py --test-db
```

Results from the development PC (10 Nov 2026) are in `docs/benchmarks/`. With PostgreSQL the
median close for 55 series took 1.33 s and the slowest 1.73 s, against the 5 s limit. **This must
be re-run on the client's ARM VM before go-live**; split the worker only if it exceeds 5 s.

## 6. Prototype walkthrough

Walk the client through the HTML prototype (scanner + chart side by side) and note their changes.

## 7. Open questions to ask

1. After a BOS, the protected low stays empty until a new swing low forms (no CHoCH possible until then). Confirm.
2. The break candle itself does not count as a touch of the new zone. Confirm.
3. The first entry into a zone counts as retest 1. Confirm.
4. Normal spreads: Twelve Data has no bid/ask, so `normal_spread` stays a placeholder. Please
   provide typical spreads per instrument, or confirm we measure them once OANDA is connected.
5. Default preset values (D-03) are still the developer's placeholders.
