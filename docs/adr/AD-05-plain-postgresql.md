# AD-05: Plain PostgreSQL 16, no TimescaleDB

- **Status:** Accepted (Software Design Document v1.0, client-approved 5 Nov 2026)
- **Source:** Software Design Document, architecture decisions table; PROJECT_HANDOFF.md section 3

## Context

About 1.5 million candle rows over two years fit plain tables with the right indexes.

## Decision

PostgreSQL 16 with ordinary tables and composite primary keys.
