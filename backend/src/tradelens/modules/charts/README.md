# charts

**Purpose:** chart payloads and candle pages (`GET /charts/{instrument}/{tf}`,
`GET /candles/{instrument}/{tf}`). History is capped by `chart_history_candles`; official
settings read stored rows; a preset the worker does not run is computed by `analysis` over
`chart_history_candles + 1,000` candles (max 3,000) in a 2-thread pool, cached 15 minutes in
Redis `chartc:*` and limited to 20 a minute per user.

| Item | Value |
| --- | --- |
| Requirements | FR-CHART-01..05, FR-CUST-04, FR-SCAN-03 (provisional swings); Detailed Design 4.2 |
| Tables (read) | `candles`, `instruments`, `series_status`, engine output tables, `presets` |
| Endpoints | `GET /api/v1/charts/{instrument}/{tf}`, `GET /api/v1/candles/{instrument}/{tf}` |
| Depends on | `core`, `analysis.public`, `market_data.public` |
| Layer | 2 |
