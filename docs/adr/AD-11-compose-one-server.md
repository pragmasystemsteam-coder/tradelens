# AD-11: Docker Compose on one free-tier server

- **Status:** Accepted (Software Design Document v1.0, client-approved 5 Nov 2026)
- **Source:** Software Design Document, architecture decisions table; PROJECT_HANDOFF.md section 3

## Context

The client deploys and operates production alone; hosting starts at zero cost.

## Decision

One Compose file runs every service; any Linux VM with Docker works.
