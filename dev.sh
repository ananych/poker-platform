#!/usr/bin/env bash
# 一鍵本機試玩：Postgres（Docker）+ API + Web
#
#   ./dev.sh          只在這台電腦玩（http://localhost:3000）
#   ./dev.sh --lan    同一個 Wi-Fi 的手機／朋友也能連（http://<你的區網IP>:3000）
#
# 需要：Python 3.11+、Node 18+、Docker Desktop（或自己準備 Postgres 並在 .env 設 POKER_DATABASE_URL）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

LAN=0
[[ "${1:-}" == "--lan" ]] && LAN=1

say() { printf '\033[1;33m▶ %s\033[0m\n' "$*"; }
die() { printf '\033[1;31m✖ %s\033[0m\n' "$*" >&2; exit 1; }

# ---------- tools ----------
PY=""
for c in python3.13 python3.12 python3.11 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
    PY="$c"; break
  fi
done
[[ -n "$PY" ]] || die "需要 Python 3.11 以上（macOS：brew install python@3.12）"
command -v node >/dev/null || die "需要 Node.js 18 以上（macOS：brew install node）"
command -v npm >/dev/null || die "需要 npm"

# ---------- .env ----------
if [[ ! -f .env ]]; then
  cp .env.example .env
  say "已建立 .env"
fi
if ! grep -q '^POKER_DATA_ENCRYPTION_KEY=.\+' .env; then
  KEY=$("$PY" -c 'import base64,secrets;print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("="))')
  if grep -q '^POKER_DATA_ENCRYPTION_KEY=' .env; then
    sed -i.bak "s|^POKER_DATA_ENCRYPTION_KEY=.*|POKER_DATA_ENCRYPTION_KEY=$KEY|" .env && rm -f .env.bak
  else
    echo "POKER_DATA_ENCRYPTION_KEY=$KEY" >> .env
  fi
  say "已產生資料加密金鑰（存在 .env，請勿外流或更換）"
fi
# shellcheck disable=SC1091
set -a; source <(grep -E '^(POKER_DATABASE_URL|POKER_DATA_ENCRYPTION_KEY)=' .env); set +a
export POKER_DATABASE_URL="${POKER_DATABASE_URL:-postgresql+asyncpg://poker:poker@localhost:5432/poker}"

# ---------- host / origins ----------
HOST=localhost
if [[ $LAN == 1 ]]; then
  HOST=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null \
         || hostname -I 2>/dev/null | awk '{print $1}' || true)
  [[ -n "$HOST" ]] || die "找不到區網 IP，請確認已連上 Wi-Fi"
fi
WEB="http://$HOST:3000"
API="http://$HOST:8000"
export POKER_ENV=dev POKER_COOKIE_SECURE=false
export POKER_ALLOWED_ORIGINS="[\"http://localhost:3000\",\"$WEB\"]"
export NEXT_PUBLIC_API_BASE="$API"

# ---------- database ----------
db_ready() {
  (cd services/api && .venv/bin/python - <<'EOF' >/dev/null 2>&1
import asyncio, os, asyncpg
url = os.environ["POKER_DATABASE_URL"].replace("postgresql+asyncpg", "postgresql")
async def main():
    c = await asyncpg.connect(url, timeout=3); await c.close()
asyncio.run(main())
EOF
  )
}

# ---------- python deps (needed for db check) ----------
if [[ ! -x services/api/.venv/bin/python ]]; then
  say "建立 Python 虛擬環境"
  "$PY" -m venv services/api/.venv
fi
if [[ ! -f services/api/.venv/.installed ]] || [[ services/api/pyproject.toml -nt services/api/.venv/.installed ]]; then
  say "安裝後端套件（第一次約 1 分鐘）"
  services/api/.venv/bin/pip install -q --upgrade pip
  services/api/.venv/bin/pip install -q -e "services/api[dev]"
  touch services/api/.venv/.installed
fi

if ! db_ready; then
  if command -v docker >/dev/null 2>&1; then
    say "啟動 Postgres（Docker）"
    docker compose -f infra/docker-compose.yml up -d db
    for _ in $(seq 1 40); do db_ready && break; sleep 1; done
  fi
  db_ready || die "連不到 Postgres。請打開 Docker Desktop 後重試，或在 .env 設定 POKER_DATABASE_URL"
fi

say "套用資料庫 migration"
(cd services/api && .venv/bin/alembic upgrade head >/dev/null)

# ---------- web ----------
if [[ ! -d apps/web/node_modules ]]; then
  say "安裝前端套件（第一次約 1 分鐘）"
  (cd apps/web && npm install --no-audit --no-fund >/dev/null)
fi
say "建置前端（約 30–60 秒）"
(cd apps/web && npm run build >/dev/null && rm -rf .next/standalone/.next/static \
   && cp -r .next/static .next/standalone/.next/static)

# ---------- run ----------
cleanup() { [[ -n "${API_PID:-}" ]] && kill "$API_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

say "啟動 API  → $API"
(cd services/api && exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 \
   --log-level warning) &
API_PID=$!
for _ in $(seq 1 30); do curl -fsS "http://localhost:8000/health/ready" >/dev/null 2>&1 && break; sleep 0.5; done

cat <<EOF

  ♠ ♥ 可以開始試玩了 ♦ ♣

  打開瀏覽器： $WEB
$( [[ $LAN == 1 ]] && echo "  同一個 Wi-Fi 的手機也能用這個網址加入" )
  建立房間後，把「邀請連結」和房間密碼傳給朋友。
  一個人測試：用一般視窗＋無痕視窗，當作兩位玩家。

  按 Ctrl+C 結束
EOF
cd apps/web && HOSTNAME=0.0.0.0 PORT=3000 node .next/standalone/server.js
