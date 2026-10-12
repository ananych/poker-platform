# Operations runbook

## Health & metrics (SDD §12)

- `GET /health/live` — process up. `GET /health/ready` — DB reachable and startup recovery
  finished (503 while starting or shutting down).
- `GET /metrics` with `Authorization: Bearer $POKER_METRICS_TOKEN` (JSON):
  - counters: `hands_completed`, `timeouts`, `ws_connects`, `ws_disconnects`,
    `rejected.<CODE>` (e.g. `rejected.STALE_VERSION` = version-conflict rate),
    `invariant_failures` (**page on any non-zero**)
  - latency p50/p95/max: `room_tx` (DB transaction), `ws_action_roundtrip`
  - gauges: `ws_connections`, `rooms_with_connections`

Logs never contain hole cards, session cookies or invite tokens.

## Paused room (PAUSED_RECOVERY)

Cause: API restart with an unfinished hand (or an empty room hit the 24 h close while a hand
was still live). State is frozen exactly at the last commit. Resolution: the current host
presses Resume. If nobody eligible is connected the room stays paused indefinitely (A-10) —
chips are never forfeited automatically.

## Backups (SDD §12)

Nightly `pg_dump -Fc` (or the managed provider's PITR). At least monthly, run the drill:

```bash
PGURL=postgresql://user:pass@host:5432/poker POKER_DATA_ENCRYPTION_KEY=... \
  services/api/scripts/backup_restore_drill.sh
```

It restores into a scratch DB, checks migrations are at head, and runs
`scripts/verify_backup.py` (ledger conservation per room, snapshot decryption with the
current key, engine invariants, contiguous event sequences, payouts == pot).
Exit code ≠ 0 means investigate before trusting that backup.

## Capacity gate (SDD §13.3)

```bash
# against a staging API started with POKER_GUEST_SESSIONS_PER_IP_PER_MINUTE=1000
python services/api/scripts/loadtest.py --base https://staging.example.com --users 30 --seconds 120
```

Pass criteria: every room's clients converge on the same `room_version` as the REST view,
ledger nets sum to 0 per room, no unexpected rejections. Reference run (single container,
local Postgres): 30 users / 5 rooms / 60 s → ~96 hands, ~1.9 k actions,
action round-trip p50 ≈ 50 ms, p95 ≈ 115 ms.

## Retention (A-07/A-08)

Hourly job deletes expired guest sessions and chat older than `POKER_CHAT_RETENTION_DAYS`
(default 30). Hands, hand events and the chip ledger are kept; closed rooms are archived,
not deleted.
