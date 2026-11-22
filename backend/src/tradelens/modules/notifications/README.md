# notifications

E-mail outbox (DD 2.6 `email_outbox`, DD-7; task 3.1). In-app notifications (`notifications` table) and alert deliveries arrive with task 3.7.

| Piece | What it does |
| --- | --- |
| `enqueue_email(conn, kind, to, subject, payload, dedupe_key=None)` | Queues a row in the caller's transaction. Same `dedupe_key` = same row. |
| `queue_email(conn, kind, to, payload)` | As above, subject taken from the template (also checks every placeholder is present). |
| `compose(kind, payload)` | Renders `templates/<kind>.txt` (`Subject:` line, blank line, body; `$name` placeholders). |
| `deliver_due(begin, transport, now, max_attempts=)` | Claims due rows (`FOR UPDATE SKIP LOCKED`), sends, records sent / retry / failed. Called by `worker/mailer.py` every 5 s. |

Retries after 1 min, 5 min, 30 min, then every 2 h, until `EMAIL_OUTBOX_MAX_ATTEMPTS` (default 5) attempts; then `failed`. A row left in `sending` for 5 minutes is claimed again. `link` and `reset_link` are removed from the payload once sent (they carry one-time tokens).

Transports live in `integrations/email.py`: `EMAIL_TRANSPORT=smtp` (Brevo relay, STARTTLS) or `console` (logs the mail; allowed only with `APP_ENV=development` or `test`).

This module sits in the lowest layer, so accounts, billing and alerts can all queue mail.
