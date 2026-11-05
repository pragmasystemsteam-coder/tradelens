# market_data

**Purpose:** owns the instrument catalogue, trading calendars, candles, per-series status and
gap history. Day 1: validated reference data and its idempotent seed. Ingestion, gap detection
and backfill arrive in tasks 1.8–1.9.

| Item | Value |
| --- | --- |
| Requirements | FR-DATA-01..09, DR-01..DR-05; Detailed Design 2.4, 6.4, 6.5 |
| Tables | `trading_calendars`, `instruments`, `candles`, `series_status`, `data_gaps` |
| Endpoints | none yet (`/api/v1/instruments` in Increment 2) |
| Depends on | `core` only |
| Layer | 6 (lowest; imports no other module) |
| Consumed via | `public.py`: `build_reference_rows`, `save_reference_rows`, `TIMEFRAMES` |

Key files: `service.py` (validation: keys, scales, calendars), `repository.py` (insert-only SQL).
Rule: the seed never updates an instrument, because changing `price_scale` under stored candles
corrupts prices.
