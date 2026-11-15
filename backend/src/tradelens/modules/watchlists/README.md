# watchlists

**Purpose:** per-user instrument lists with last price, data status and best setup. Counts are
checked against `max_watchlists` / `max_watchlist_items` with the owner row locked; another
user's list answers 404 (NFR-10).

| Item | Value |
| --- | --- |
| Requirements | FR-WATCH-01, FR-WATCH-02; Detailed Design 4.2, 4.3 |
| Tables | `watchlists`, `watchlist_items` |
| Endpoints | `GET/POST /api/v1/watchlists`, `GET/PATCH/DELETE /api/v1/watchlists/{id}`, `PUT/DELETE /api/v1/watchlists/{id}/items/{instrument}` |
| Depends on | `core`, `market_data.public`, `scanner.public` |
| Layer | 2 |
