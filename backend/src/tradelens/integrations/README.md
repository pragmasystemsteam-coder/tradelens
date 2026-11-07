# integrations

Adapters that implement module ports (ADR-0001). Modules never import this package; the worker
and the CLI wire it (`providers.build_candle_provider`).

| Package | Implements | Notes |
| --- | --- | --- |
| `twelvedata/` | `market_data.ports.CandleProvider` | CR-004. `/time_series` with `timezone=UTC`, `order=ASC`, `dp` = price scale. The key is sent in the `Authorization: apikey` header and redacted from errors. `CreditLimiter`: 8 credits/minute, 800/UTC day (FREE plan). |
| `fakes/synthetic.py` | `CandleProvider` | Deterministic integer bars for every instrument (15m/1h are exact aggregates of 5m). Used for every series outside the live subset. |
| `fakes/recorded.py` | `CandleProvider` | Replays saved Twelve Data responses (tests, offline work). |
| `providers.py` | factory | `MARKET_DATA_PROVIDER` = `fake` or `twelvedata`; `TWELVEDATA_LIVE_INSTRUMENTS` (default `EUR_USD,XAU_USD`, `all` = every instrument; production requires `all`). |

OANDA (`oanda/`) is added when its account is verified; until then `doctor` rejects
`MARKET_DATA_PROVIDER=oanda`.
