# accounts

**Purpose:** users and their sign-in state. Day 4 (task 2.1): the `users`, `sessions` and
`email_tokens` tables (migration 0002) and `create_account` for the operator command
`create-user`. Sign-in, sessions, CSRF and rate limits arrive in task 2.4; sign-up, verification,
reset and deletion in Increment 3.

| Item | Value |
| --- | --- |
| Requirements | FR-ACC-04..06 (later tasks); Detailed Design 2.1, 4.1 |
| Tables | `users`, `sessions`, `email_tokens` |
| Endpoints | none yet (`/auth/*` in task 2.4) |
| Depends on | `core` |
| Layer | 6 (lowest; imports no other module) |
| Consumed via | `public.py`: `create_account`, `AccountError`, `ROLES` |

Passwords are stored only as Argon2id hashes (`cli/create_user.py` hashes; this module never sees
a password). E-mail is `citext` and unique among live users, so a deleted account's address can
register again (FR-ACC-06).
