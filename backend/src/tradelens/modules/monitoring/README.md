# monitoring

**Purpose:** health of the running system. Day 1: `GET /healthz` for Docker. Later: `/healthz/full`
(worker heartbeat, data freshness, task 1.9), admin system status and monitoring alerts (task 3.8, CR-002).

| Item | Value |
| --- | --- |
| Requirements | FR-ADM-12 (later), NFR-05; Detailed Design 4.8 |
| Tables | none yet (`monitor_alert_state` arrives in Increment 3) |
| Endpoints | `GET /healthz` → 200 `{"status":"ok"}` or 503 `{"status":"error","db":…,"redis":…}` |
| Depends on | `core.db`, `core.redis` |
| Layer | 1 (may import any module below it through `public.py`) |

Key files: `service.py` (`HealthChecks`, `InfraHealthChecks`, `run_checks`), `router.py` (thin route;
`get_checks` is wired in `app/bootstrap.py`).
