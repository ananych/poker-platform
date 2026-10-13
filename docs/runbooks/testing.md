# Testing

| Layer | Command | Covers |
|---|---|---|
| Engine unit + property | `cd services/api && pytest tests/unit tests/property` | evaluator vs independent oracle, side pots, odd chips, short all-in reopen rules, conservation over random legal hands |
| Integration (Postgres) | `POKER_TEST_DATABASE_URL=postgresql+asyncpg://... pytest tests/integration` | REST/WS contracts, duplicate action ids, stale versions, action-vs-timeout race, concurrent start, recovery/resume, host election, bans, privacy, history redaction, chat |
| E2E (Playwright) | see below | phone (390×844) host + desktop guest: create → invite → wrong password → join → sit → play → result → chat → replay; tap targets ≥ 40 px; no horizontal scroll |
| Capacity | `python scripts/loadtest.py` | 30 users over real WS (see operations.md) |
| Backup | `scripts/backup_restore_drill.sh` | restore + invariant verification |

## E2E (Playwright)

Run against a production-like stack: one origin, like the Railway gateway
(`/api`, `/ws`, `/health` → API; everything else → web).

```bash
# 1) API with test-friendly timings (12 s turns, 5 s host grace, 1 min sit-out limit)
cd services/api && POKER_ENV=prod POKER_COOKIE_SECURE=false \
  POKER_DATA_ENCRYPTION_KEY=$(python -c 'import base64,secrets;print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("="))') \
  POKER_ALLOWED_ORIGINS='["http://localhost:8080"]' POKER_ACTION_TIMEOUT_SECONDS=12 \
  POKER_HOST_DISCONNECT_GRACE_SECONDS=5 POKER_SIT_OUT_STAND_UP_MINUTES=1 \
  POKER_GUEST_SESSIONS_PER_IP_PER_MINUTE=100000 python -m app.serve
# 2) web, same-origin build (NEXT_PUBLIC_API_BASE empty)
cd apps/web && npm run build && cp -r .next/static .next/standalone/.next/ \
  && HOSTNAME=127.0.0.1 PORT=3000 node .next/standalone/server.js
# 3) same-origin gateway on :8080
node infra/e2e/gateway.mjs
# 4) tests (one worker: several tests wait on real timers)
cd apps/web && E2E_BASE_URL=http://localhost:8080 npx playwright test --workers=1
# server-restart tests need a command that restarts the API process:
RESTART_API="<command that restarts the API process>" E2E_BASE_URL=http://localhost:8080 npx playwright test e2e/recovery.spec.ts
```

| Spec | Covers |
|---|---|
| `table.spec.ts` | phone host + desktop guest: create → invite → wrong password → join → sit → play → showdown (own cards, winner, net) → chat bubble/toast → auto-deal → pre-action → English → standings → replay |
| `features.spec.ts` | lobby validation & buy-in limits; 3-way all-in side pots + conservation; every pre-action and its invalidation; timeout → fold + sit out → back in; auto-deal / deal now / pause / resume; host leaves → hand finishes, new host, dealing continues, idle player stood up; chat (escaping, unread, rate limit); top-ups; mid-hand settings; kick / ban / unban / transfer; standings pop, history, replay, ledger; English with no untranslated UI; settings & audio; leave mid-hand; spectator privacy; invite rotation, nickname change, re-sitting |
| `recovery.spec.ts` | API restart mid-hand (clients reconnect, hand frozen, host resumes) and between hands (auto-deal continues) |
| `ui.spec.ts` | 9-handed table with long/mixed names on 320/390/412 phones, landscape phone, tablets, laptop, desktop, 4K: no horizontal scroll, no clipped seats, no overlapping seats or bet chips; my-turn controls and seat menu ≥ 40 px; lobby/join at 320 px. Screenshots go to `$E2E_SHOTS` |
