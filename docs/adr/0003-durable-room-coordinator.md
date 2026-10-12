# ADR 0003 — Durable room coordinator (Phase 2)

- Status: Accepted
- Date: 2026-10-10

## Decision
Every room mutation runs in `app/services/uow.room_tx`:

1. acquire the in-process per-room `asyncio.Lock`;
2. open a transaction and `SELECT … FROM rooms … FOR UPDATE`;
3. validate (membership/ban, host, `expected_room_version`, paused, deadline, idempotency);
4. run the pure engine; write the encrypted hand snapshot, `hand_players`, materialized
   `table_seats.stack`, append-only `hand_events`, ledger rows and the `action_results` dedup row;
5. bump `rooms.version` once per durable transition and commit;
6. after commit (mutex still held): schedule the action timer, then publish per-recipient
   projections over WebSocket.

A unique partial index guarantees at most one unfinished hand per room; `hands(room_id,
idempotency_key)` makes Start Hand retries safe.

## Timers
Deadlines are stored in `hands.deadline_at` (server UTC). The in-process timer only proposes a
timeout; `process_timeout` re-checks hand id, room version, operational status and the deadline
under the lock, so a stale or duplicate wake-up is a no-op and can never race a player action
into a double move.

## Recovery
On startup every room with an unfinished hand becomes `PAUSED_RECOVERY`, deadlines are cleared
and all members are marked disconnected. Only the current host may `resume`, which grants the
actor a fresh 30 s from resume time. If the host stays away 60 s, election picks the
earliest-joined connected member who can then resume.

## Consequences
Correct with exactly one Uvicorn worker. Scaling out needs a distributed lock or a DB-only
serialization strategy (out of scope for v1).
