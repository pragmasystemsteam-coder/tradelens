# AD-08: Custom settings calculated on demand, cached by settings hash

- **Status:** Accepted (Software Design Document v1.0, client-approved 5 Nov 2026)
- **Source:** Software Design Document, architecture decisions table; PROJECT_HANDOFF.md section 3

## Context

Only charts and watchlists (at most 7 pairs) use custom settings.

## Decision

No per-user worker pools; results cached by `settings_hash`. The scanner always uses the official settings.
