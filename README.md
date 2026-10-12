# Private Texas Hold'em — poker-platform

邀請制、瀏覽器端的無限注德州撲克現金局（虛擬整數籌碼，每桌 2–9 人，總線上 10–30 人）。
依據 `docs/Private_Texas_Holdem_SDD_v1.0`（SDD v1.0, 2026-10-10）實作。

> **產品邊界**：本系統不接受存款、不發起付款、不計算玩家間轉帳、不提供提領或真實金錢結算；只記錄虛擬籌碼。若用於有賭注的場合，需另行做當地法律審查。

## 🃏 馬上試玩（macOS）

需要：Python 3.11+、Node 18+、Docker Desktop（用來跑 Postgres）。

```bash
cd ~/Desktop/Git/poker-platform
./dev.sh          # 只在這台電腦：http://localhost:3000
./dev.sh --lan    # 同一個 Wi-Fi 的手機／朋友也能連：http://<區網IP>:3000
```

第一次會自動建立 `.env`（含加密金鑰）、安裝套件、啟動資料庫、建置前端，約 2–3 分鐘。
一個人測試：一般視窗＋無痕視窗當兩位玩家。按 Ctrl+C 結束。

## ☁️ 部署到 Railway

照 [`docs/runbooks/railway.md`](docs/runbooks/railway.md)：Postgres ＋ `api`、`web`、`gateway` 三個服務，只有 gateway 對外（同一個網域，cookie 與 WebSocket 才能正常運作）。

## 架構（SDD §1、§14）

Modular monolith：Next.js/TypeScript/Tailwind 前端 + FastAPI/Python 後端 + PostgreSQL，單一常駐後端實例、單一 worker。

```
apps/web/                 Next.js client (lobby, table, chat, replay)
services/api/app/
  api/                    REST controllers, auth deps, CSRF, error envelope
  realtime/               WebSocket gateway, background sweeper
  domain/poker/           PURE engine: state machine, evaluator, pots
  services/               guests, rooms, table (hands/actions), views, timers, uow
  persistence/            SQLAlchemy models, DB session
  security/               tokens, Argon2id, AES-GCM, rate limits
services/api/migrations/  Alembic
services/api/tests/       unit / property / integration
infra/                    docker-compose, initdb
docs/                     ADR、決策紀錄、協定文件
```

依賴方向：transport → application services → pure domain。`domain/poker` 不得 import FastAPI / SQLAlchemy / WebSocket（有測試守門：`tests/unit/test_architecture.py`）。

## 快速開始

```bash
cp .env.example .env
# 產生資料加密金鑰並填入 POKER_DATA_ENCRYPTION_KEY
docker compose -f infra/docker-compose.yml up -d db

cd services/api
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -c "from app.security.crypto import Cipher; print(Cipher.generate_key())"
export POKER_DATABASE_URL=postgresql+asyncpg://poker:poker@localhost:5432/poker
alembic upgrade head
uvicorn app.main:app --reload --workers 1          # http://localhost:8000/api/docs

# 測試（整合測試需要 POKER_TEST_DATABASE_URL）
export POKER_TEST_DATABASE_URL=postgresql+asyncpg://poker:poker@localhost:5432/poker_test
pytest -q

cd ../../apps/web && npm install
NEXT_PUBLIC_API_BASE=http://localhost:8000 npm run dev   # http://localhost:3000
```

本機 http 開發時設定 `POKER_COOKIE_SECURE=false`；正式環境必須走 HTTPS/WSS。

> ⚠️ `POKER_DATA_ENCRYPTION_KEY` 一旦有牌局在進行就不能更換；換了金鑰，進行中的牌局在重啟後無法解密恢復。

## API 速覽

REST（`/api/v1`，狀態變更需 `X-Poker-CSRF: 1`）：`POST /rooms`、`POST /rooms/{id}/join`、`GET /rooms/{id}`、
`POST /rooms/{id}/seats/{n}`、`/sit-out`、`/leave`、`/topups`、`/topups/{rid}/approve`、`/start-hand`、`/resume`、
`PATCH /rooms/{id}/config`、`/members/{mid}/ban`、`/members/{mid}/kick`、`DELETE /bans/{mid}`、`/transfer-host`、`GET /ledger`。

另有 `POST /rooms/{id}/invite`（產生新邀請連結）、`GET /rooms/{id}/hands`、`GET /rooms/{id}/hands/{hid}`（回放）、`GET|POST /rooms/{id}/chat`、`GET /metrics`。

WebSocket：`/ws/rooms/{room_id}`（cookie + Origin），協定見 `docs/ws-protocol.md`。

## 進度（SDD §15）

| Phase | 內容 | 狀態 |
|---|---|---|
| 0 Foundation | Repo、CI、Docker、Postgres migrations、guest session | ✅ |
| 1 Rules engine | 狀態機、CSPRNG 洗牌、評牌器、下注驗證、邊池 | ✅ property tests |
| 2 Durable multiplayer | 房間/座位/房主、加密 snapshot、籌碼 ledger、30 秒計時器、WebSocket | ✅ 並發測試 |
| 3 Player experience | 手機直式優先＋桌面牌桌、大廳、邀請＋密碼、聊天 | ✅ Playwright（手機＋桌面） |
| 4 Admin + archive | 房主控制、補碼、封鎖、歷史＋回放（遮蔽未亮牌）、sit-out/leave | ✅ 遮蔽測試 |
| 5 Operations | Recovery/Resume、metrics、備份演練、部署設定、30 人壓測 | ✅ 壓測通過 |

文件：`docs/runbooks/deploy.md`（部署）、`docs/runbooks/operations.md`（監控／備份／壓測）、`docs/runbooks/testing.md`（測試）。

尚待產品負責人確認的假設見 `docs/decisions.md`。
