# 部署到 Railway

架構：4 個 Railway 服務，只有 **gateway** 對外。

```
瀏覽器 ──HTTPS──> gateway (Caddy, 公開網域)
                    ├─ /api/* /ws/* /health/* ──> api.railway.internal:8000  (FastAPI，1 個 worker)
                    └─ 其他所有路徑            ──> web.railway.internal:3000  (Next.js)
                                                     api ──> Postgres (Railway 外掛)
```

> 為什麼要 gateway？`*.up.railway.app` 在 Public Suffix List 上，web 與 api 若各自有網域會被瀏覽器視為**不同網站**，
> HttpOnly + SameSite=Lax 的登入 cookie 不會送出、WebSocket Origin 也對不上。用同一個網域就沒有這些問題。

## 0. 先準備

1. 程式碼推到 GitHub（見下方「推到 GitHub」）。
2. 在自己電腦產生兩個祕密（**存好，之後不能換加密金鑰**）：
   ```bash
   # 資料加密金鑰（手牌／牌組加密用）
   python3 -c "import base64,secrets;print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip('='))"
   # metrics token
   python3 -c "import secrets;print(secrets.token_urlsafe(24))"
   ```

## 1. 建立專案與資料庫

Railway → **New Project** → **Deploy from GitHub repo** → 選 `poker-platform`。
Railway 會先建一個服務；之後依下表調整。再按 **+ Create → Database → PostgreSQL**（名稱保持 `Postgres`）。

## 2. 三個服務（同一個 repo，各自設定 Root Directory）

用 **+ Create → GitHub Repo** 加服務，**服務名稱必須是 `api`、`web`、`gateway`**（gateway 靠名稱找內網位址）。

| 服務 | Settings → Root Directory | 對外網域 | Watch Paths（選填） |
|---|---|---|---|
| `api` | `services/api` | 不要 | `/services/api/**` |
| `web` | `apps/web` | 不要 | `/apps/web/**` |
| `gateway` | `infra/railway/gateway` | **Generate Domain**，port 填 `8080` | `/infra/railway/**` |

三個都會自動偵測到該目錄裡的 `Dockerfile`。

## 3. 環境變數（Variables 分頁，可用 Raw Editor 貼上）

**api**
```
POKER_ENV=prod
POKER_DATABASE_URL=${{Postgres.DATABASE_URL}}
POKER_DATA_ENCRYPTION_KEY=<步驟 0 產生的金鑰>
POKER_METRICS_TOKEN=<步驟 0 產生的 token>
POKER_ALLOWED_ORIGINS=["https://${{gateway.RAILWAY_PUBLIC_DOMAIN}}"]
POKER_COOKIE_SECURE=true
PORT=8000
```

**web**
```
PORT=3000
```

**gateway**
```
PORT=8080
```

（gateway 預設轉送到 `api.railway.internal:8000` 與 `web.railway.internal:3000`；
如果服務名稱不同，設定 `API_UPSTREAM`、`WEB_UPSTREAM` 覆蓋。）

## 4. api 服務的部署設定（Settings → Deploy）

- **Healthcheck Path**：`/health/ready`
- **Replicas：1**（一定只能 1 個；房間序列化在單一程序內）
- **Serverless / App Sleeping：關閉**（WebSocket 與 30 秒計時器需要常駐）
- Restart policy：On failure

API 啟動時會自動跑 `alembic upgrade head`，不用手動 migrate。

## 5. 驗證

打開 `https://<gateway 網域>`：
- `https://<gateway 網域>/health/ready` → `{"status":"ok","db":true}`
- 建房 → 用無痕視窗開邀請連結 → 兩人坐下 → 打一手

## 之後更新

`git push` 到 main，Railway 會自動重建有變動的服務。API 重新部署時進行中的牌局會暫停，
房主在牌桌上按「繼續牌局」即可（見 `operations.md`）。

## 常見問題

| 症狀 | 檢查 |
|---|---|
| 一直要重新輸入暱稱／401 | 是否從 gateway 網域開啟（不是 api/web 的網域）；`POKER_ALLOWED_ORIGINS` 是否是 gateway 的 https 網址 |
| WebSocket 連不上（右上角黃燈） | 同上；api 是否 healthy |
| 502 Bad Gateway | api/web 服務名稱是否正確、是否已部署成功；`PORT` 變數是否設好 |
| api 啟動失敗 `POKER_DATA_ENCRYPTION_KEY is required` | 變數沒設；prod 模式一定要有 |
| `/metrics` | 不對外公開；需要時在 Railway 內網用 `Authorization: Bearer <token>` 存取 |
