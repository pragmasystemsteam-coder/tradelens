# Architecture decision records

AD-01..AD-14 are copied from the approved Software Design Document. ADR-0001 refines SDD section 10.
New decisions get the next `NNNN-title.md` number and a line here.

| Record | Decision | Status |
| --- | --- | --- |
| [ADR-0001](0001-feature-based-module-structure.md) | Feature-based module structure | Accepted 5 Nov 2026 |
| [AD-01](AD-01-modular-monolith.md) | Modular monolith plus one worker, not microservices | Accepted |
| [AD-02](AD-02-pure-engine-step.md) | The engine is a pure function with an incremental step() | Accepted |
| [AD-03](AD-03-one-worker.md) | One worker process for ingestion and detection | Accepted |
| [AD-04](AD-04-complete-candles.md) | Candles from OANDA's candle endpoint (complete only); stream only for the live price line | Accepted |
| [AD-05](AD-05-plain-postgresql.md) | Plain PostgreSQL 16, no TimescaleDB | Accepted |
| [AD-06](AD-06-redis-pubsub.md) | Redis publish/subscribe, not Streams | Accepted |
| [AD-07](AD-07-sse.md) | Server-Sent Events, not WebSocket | Accepted |
| [AD-08](AD-08-custom-on-demand.md) | Custom settings calculated on demand, cached by settings hash | Accepted |
| [AD-09](AD-09-server-sessions.md) | Server-side sessions in PostgreSQL with an HttpOnly cookie | Accepted |
| [AD-10](AD-10-admin-app.md) | Separate admin app on its own subdomain behind Cloudflare Access, own sign-in and TOTP | Accepted |
| [AD-11](AD-11-compose-one-server.md) | Docker Compose on one free-tier server | Accepted |
| [AD-12](AD-12-integer-prices.md) | Exact integer prices; UTC storage; New York 17:00 trading day | Accepted |
| [AD-13](AD-13-template-explanations.md) | Explanations from templates, no AI | Accepted |
| [AD-14](AD-14-lightweight-charts.md) | TradingView Lightweight Charts | Accepted |
