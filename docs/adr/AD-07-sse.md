# AD-07: Server-Sent Events, not WebSocket

- **Status:** Accepted (Software Design Document v1.0, client-approved 5 Nov 2026)
- **Source:** Software Design Document, architecture decisions table; PROJECT_HANDOFF.md section 3

## Context

Updates flow only from server to browser; SSE is simpler through Cloudflare.

## Decision

`/api/v1/stream` uses SSE; the proxy does not buffer or compress it.
