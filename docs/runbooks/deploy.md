# Deploy runbook

## Topology (SDD §1, §12)

```
Browser ──HTTPS/WSS──> Caddy ──/api,/ws,/health──> api (FastAPI, ONE worker) ──> PostgreSQL
                             └──everything else──> web (Next.js standalone)
```

One origin for web + API: the HttpOnly `SameSite=Lax; Secure` session cookie and the
WebSocket Origin check work without CORS. The provider must keep the API **always on**
(no cold sleep) and allow long-lived WebSockets.

## First deploy (single host)

```bash
cp .env.example .env.prod   # then edit:
#   DOMAIN=poker.example.com
#   POSTGRES_PASSWORD=<random>
#   POKER_DATA_ENCRYPTION_KEY=<python -c "from app.security.crypto import Cipher;print(Cipher.generate_key())">
#   POKER_METRICS_TOKEN=<random>
DOMAIN=poker.example.com docker compose -f infra/docker-compose.prod.yml --env-file .env.prod up -d --build
curl -fsS https://poker.example.com/health/ready
```

The API container runs `alembic upgrade head` before starting Uvicorn.
**Never** scale the API beyond one replica/worker (per-room serialization is in-process).

Managed Postgres: set `POKER_DATABASE_URL=postgresql+asyncpg://...` and drop the `db` service.

## Secrets

| Secret | Notes |
|---|---|
| `POKER_DATA_ENCRYPTION_KEY` | AES-256 key for hole cards/deck at rest. Keep in the secrets manager **and** an offline escrow. Losing it makes unfinished hands unrecoverable (finished hands' public history and the ledger stay readable). Do not change it while hands are live. |
| `POKER_METRICS_TOKEN` | Bearer token for `GET /metrics` (scrape on the private network). |
| `POSTGRES_PASSWORD` | DB credentials. |

## Rolling restart / redeploy

1. `docker compose ... up -d --build api` — on SIGTERM the API stops accepting new hands,
   drops readiness, closes sockets with code 1012 (clients auto-reconnect).
2. On start every room with an unfinished hand becomes `PAUSED_RECOVERY`; timers are not run.
3. Players see the paused banner; the host taps **繼續牌局 (Resume)**, which gives the actor a
   fresh 30 s. If the host is gone 60 s, the earliest-joined connected member becomes host.

## Smoke after deploy

- `GET /health/live` → 200, `GET /health/ready` → 200 (`db: true`)
- Create a room from a phone, join from a second browser, play one hand.
