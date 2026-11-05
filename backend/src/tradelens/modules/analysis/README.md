# analysis

**Purpose:** the only module that runs `tradelens_engine` and writes its output. Day 1: rule
versions and presets (validated by the engine's `Settings`, hashed with `settings_hash`) and
their idempotent seed. Series state, events, liquidity, zones and setups arrive in tasks 1.6–1.9
and Increment 2.

| Item | Value |
| --- | --- |
| Requirements | FR-SMC-11, FR-SMC-12, FR-CUST-04, FR-CUST-08; Detailed Design 2.5, 3, 6.3 |
| Tables | `rule_versions`, `presets`, `series_state`, `market_events`, `liquidity_levels`, `zones`, `zone_transitions` (later `setups`, `setup_revisions`) |
| Endpoints | none yet |
| Depends on | `core`, `tradelens_engine` |
| Layer | 4 (may import billing and layer-6 modules through their `public.py`) |
| Consumed via | `public.py`: `build_rule_rows`, `save_rule_rows`, `RuleConfigError` |

Key files: `service.py` (rule file validation, preset hashes, activation rule), `repository.py`
(insert-only SQL). A rule version is never overwritten; the `rule_versions_guard` trigger enforces it.
