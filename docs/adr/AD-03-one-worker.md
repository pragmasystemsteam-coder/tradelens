# AD-03: One worker process for ingestion and detection

- **Status:** Accepted (Software Design Document v1.0, client-approved 5 Nov 2026)
- **Source:** Software Design Document, architecture decisions table; PROJECT_HANDOFF.md section 3

## Context

55 series per close take milliseconds of CPU; the bottleneck is I/O.

## Decision

One worker process. Split only if processing a close exceeds 5 s (benchmark in task 1.10).
