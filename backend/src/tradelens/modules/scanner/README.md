# scanner

**Purpose:** read-only ranked setups and setup detail (`GET /setups`, `GET /setups/{id}`).
Rows come from the worker's Redis lists `scanner:{direction}:{timeframe}` and fall back to the
database; filters, the asset-class gate and the keyset cursor (combined, confirm time, id) run
in `service.py` so both sources behave alike. Only confirmed setups of the official settings.

| Item | Value |
| --- | --- |
| Requirements | FR-SCAN-01..06, FR-CHART-03 (C locked on `mtf_detail: strip`); Detailed Design 4.2 |
| Tables (read) | `setups`, `setup_revisions`, `zones`, `instruments`, `series_state`, `series_status` |
| Endpoints | `GET /api/v1/setups`, `GET /api/v1/setups/{id}` |
| Depends on | `core`, `analysis.public` |
| Layer | 3 |
| Consumed via | `public.py`: `best_setups` (watchlists) |
