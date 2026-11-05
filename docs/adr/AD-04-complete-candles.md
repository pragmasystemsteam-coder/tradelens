# AD-04: Candles from OANDA's candle endpoint (complete only); stream only for the live price line

- **Status:** Accepted (Software Design Document v1.0, client-approved 5 Nov 2026)
- **Source:** Software Design Document, architecture decisions table; PROJECT_HANDOFF.md section 3

## Context

The price stream is sampled (at most 4 prices/s) and can miss highs and lows.

## Decision

Only `complete=true` candles are stored and analysed; the stream feeds only the live price display.
