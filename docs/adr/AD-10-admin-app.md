# AD-10: Separate admin app on its own subdomain behind Cloudflare Access, own sign-in and TOTP

- **Status:** Accepted (Software Design Document v1.0, client-approved 5 Nov 2026)
- **Source:** Software Design Document, architecture decisions table; PROJECT_HANDOFF.md section 3

## Context

The client asked for no public /admin path; admins approve refunds.

## Decision

`admin-web` on admin.tradelens.com, Cloudflare Access in front, admin sign-in with TOTP; the API re-checks the Access token.
