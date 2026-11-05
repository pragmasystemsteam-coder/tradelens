# AD-06: Redis publish/subscribe, not Streams

- **Status:** Accepted (Software Design Document v1.0, client-approved 5 Nov 2026)
- **Source:** Software Design Document, architecture decisions table; PROJECT_HANDOFF.md section 3

## Context

Browsers refetch after any reconnect, so a missed message costs nothing.

## Decision

Redis 7 pub/sub for live updates; Redis also holds cache, rate limits and the worker heartbeat.
