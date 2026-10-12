#!/usr/bin/env bash
# Backup/restore drill (SDD §12): dump the live DB, restore into a scratch DB,
# run migrations check + invariant verification, then drop the scratch copy.
#
#   PGURL=postgresql://user:pass@host:5432/poker \
#   POKER_DATA_ENCRYPTION_KEY=... ./scripts/backup_restore_drill.sh
set -euo pipefail
: "${PGURL:?set PGURL (libpq URL of the source database)}"
: "${POKER_DATA_ENCRYPTION_KEY:?set the same data key the app uses}"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
DUMP=${DUMP_DIR:-/tmp}/poker-$STAMP.dump
SCRATCH=poker_restore_${STAMP,,}
BASE=${PGURL%/*}

echo "== dump -> $DUMP"
pg_dump --format=custom --no-owner --file "$DUMP" "$PGURL"
echo "== restore -> $SCRATCH"
psql "$BASE/postgres" -q -c "CREATE DATABASE $SCRATCH"
trap 'psql "$BASE/postgres" -q -c "DROP DATABASE IF EXISTS $SCRATCH" || true' EXIT
pg_restore --no-owner --dbname "$BASE/$SCRATCH" "$DUMP"

ASYNC_URL="${BASE/postgresql:/postgresql+asyncpg:}/$SCRATCH"
cd "$(dirname "$0")/.."
echo "== migrations at head?"
POKER_DATABASE_URL="$ASYNC_URL" alembic current
POKER_DATABASE_URL="$ASYNC_URL" alembic check
echo "== verify invariants"
POKER_ENV=prod POKER_DATABASE_URL="$ASYNC_URL" python scripts/verify_backup.py
echo "== drill OK (dump kept at $DUMP)"
