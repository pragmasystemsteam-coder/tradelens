# AD-01: Modular monolith plus one worker, not microservices

- **Status:** Accepted (Software Design Document v1.0, client-approved 5 Nov 2026)
- **Source:** Software Design Document, architecture decisions table; PROJECT_HANDOFF.md section 3

## Context

A solo developer delivers in 14 days; the research itself rated microservices lowest.

## Decision

One backend codebase and image; the API and the worker are two processes of it. Modules keep boundaries (ADR-0001) so a module could be split out later.
