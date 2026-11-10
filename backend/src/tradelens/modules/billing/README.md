# billing

**Purpose:** plans are data (DD-2, CR-003). Day 4 (task 2.1): the plan loader for
`config/plans.json`, its idempotent upsert (`load-plans`, also run by `seed`) and manual
subscriptions for `create-user`. Entitlements (task 2.4), Razorpay checkout and webhooks,
trial and founder offer arrive in Increments 2 and 3.

| Item | Value |
| --- | --- |
| Requirements | FR-SUB-01, FR-SUB-09 (founder cap), CR-003; Detailed Design 2.2, 2.3, 6.2 |
| Tables | `plans`, `plan_prices`, `country_currency`, `founder_slots`, `subscriptions` |
| Endpoints | none yet |
| Depends on | `core` |
| Layer | 5 (may import layer-6 modules through their `public.py`) |
| Consumed via | `public.py`: `build_plan_rows`, `save_plan_rows`, `PlanConfigError`, `LIMIT_KEYS`, `plan_is_default`, `create_manual_subscription` |

Rules enforced by the loader: exactly one default (free) plan, at most one trial plan, a closed
list of limit keys with types (`null` count = unlimited; a missing key means the default in DD 6.2),
prices in minor units, `renews_into` must exist, and a `*` row in `country_currency`. The database
repeats the one-default and one-trial rules as unique indexes.
