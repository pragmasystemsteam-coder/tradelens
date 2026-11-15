# realtime

**Purpose:** Server-Sent Events (`GET /stream`) fed by Redis pub/sub: `scanner.updated`,
`chart.updated`, `price` (at most every 500 ms per instrument, latest wins),
`series.delayed`/`series.resumed`, `session.ended`; a `: ping` every 25 s; at most 6 streams per
user (`sse:{user_id}`). A topic outside the user's asset classes is refused before streaming.

| Item | Value |
| --- | --- |
| Requirements | Detailed Design 4.4; AD-06, AD-07 |
| Endpoints | `GET /api/v1/stream?topics=scanner,chart:X,price:X` |
| Depends on | `core` |
| Layer | 6 |
