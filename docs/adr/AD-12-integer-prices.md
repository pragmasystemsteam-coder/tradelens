# AD-12: Exact integer prices; UTC storage; New York 17:00 trading day

- **Status:** Accepted (Software Design Document v1.0, client-approved 5 Nov 2026)
- **Source:** Software Design Document, architecture decisions table; PROJECT_HANDOFF.md section 3

## Context

Boundary comparisons must be exact and daily candles must match the market day.

## Decision

Prices are integers in each instrument's smallest unit (decided 5 Nov 2026, replacing Decimal); ATR x1000, multipliers in thousandths, cross-multiplication. Times are UTC; the trading day starts 17:00 New York.
