# AD-09: Server-side sessions in PostgreSQL with an HttpOnly cookie

- **Status:** Accepted (Software Design Document v1.0, client-approved 5 Nov 2026)
- **Source:** Software Design Document, architecture decisions table; PROJECT_HANDOFF.md section 3

## Context

Sessions must be revocable instantly and unreadable by scripts.

## Decision

Session table keyed by an HMAC of the cookie value; cookie is HttpOnly, Secure, SameSite.
