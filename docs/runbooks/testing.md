# Testing

| Layer | Command | Covers |
|---|---|---|
| Engine unit + property | `cd services/api && pytest tests/unit tests/property` | evaluator vs independent oracle, side pots, odd chips, short all-in reopen rules, conservation over random legal hands |
| Integration (Postgres) | `POKER_TEST_DATABASE_URL=postgresql+asyncpg://... pytest tests/integration` | REST/WS contracts, duplicate action ids, stale versions, action-vs-timeout race, concurrent start, recovery/resume, host election, bans, privacy, history redaction, chat |
| E2E (Playwright) | see below | phone (390×844) host + desktop guest: create → invite → wrong password → join → sit → play → result → chat → replay; tap targets ≥ 40 px; no horizontal scroll |
| Capacity | `python scripts/loadtest.py` | 30 users over real WS (see operations.md) |
| Backup | `scripts/backup_restore_drill.sh` | restore + invariant verification |

E2E:

```bash
# terminal 1 (API, http dev cookies)
cd services/api && POKER_COOKIE_SECURE=false POKER_ENV=dev uvicorn app.main:app --port 8000
# terminal 2 (web built against the API)
cd apps/web && NEXT_PUBLIC_API_BASE=http://localhost:8000 npm run build && npm start
# terminal 3
cd apps/web && npx playwright install chromium && npm run e2e
```
