# market_data

**Purpose:** owns the instrument catalogue, trading calendars, candles, per-series status and
gap history. Day 1: validated reference data and its seed. Day 2: candle ingestion (CR-004).

| Item | Value |
| --- | --- |
| Requirements | FR-DATA-01..09, DR-01..DR-05; Detailed Design 2.4, 6.4, 6.5; CR-004 |
| Tables | `trading_calendars`, `instruments`, `candles`, `series_status`, `data_gaps` |
| Endpoints | none yet (`/api/v1/instruments` in Increment 2) |
| Depends on | `core` only; providers come in through `ports.py` |
| Layer | 6 (lowest; imports no other module) |
| Consumed via | `public.py`: reference rows, `load_instrument_specs`, `IngestService`, `SqlCandleStore`, `Calendar` |

## Key files

| File | Role |
| --- | --- |
| `ports.py` | `CandleProvider` port, `RawBar`, provider errors |
| `candles.py` | exact price parsing (no floats), the completed-candle rule, `StoredCandle` |
| `calendar.py` | open hours, expected candles, 17:00 New York buckets (DST-aware), gaps |
| `aggregate.py` | 15m/1h from 5m, 4h/1d from 1h; a bucket is built only when complete |
| `ingest.py` | `IngestService`: history once, live 5m, gaps/backfill, derived series, status |
| `candle_store.py` | PostgreSQL `CandleStore` (all candle SQL) |
| `service.py`, `repository.py` | reference data validation and seed SQL |

## Ingest rules (one pass per instrument, every 5 minutes)

1. History for 5m, 15m and 1h is fetched once, when nothing is stored (`BACKFILL_MIN_CANDLES`).
2. Afterwards only 5m is fetched, from the last stored candle (FREE plan budget, D2-1).
3. A bar is stored only when it has closed and the calendar expects it (weekend bars dropped).
4. A missing 5m candle with a later one stored is a gap: `data_gaps` row, backfill, series
   `delayed`; once filled, `filled_at` is set and the series is `ok`. A gap the provider still
   cannot fill after 30 minutes is logged and stops delaying the series.
5. Derived buckets are rebuilt over the last 3 days, so a late source candle still completes them.
6. All five series of the instrument get the same status; `delayed` keeps its first `delayed_since`.

The worker runs the pass on an AUTOCOMMIT connection (no transaction is held while the provider
or the credit limiter waits); every write is idempotent.
