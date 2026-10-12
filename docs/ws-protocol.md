# WebSocket protocol v1 (SDD §8) — implemented in Phase 2

`wss://<host>/ws/rooms/{room_id}` — authenticated with the HttpOnly session cookie and an
Origin allow-list. No tokens in query strings. Close codes: `4401` no/invalid session,
`4403` bad Origin, not a member, or banned (also sent when a member is banned while connected),
`1012` server restarting (reconnect with backoff).

## Client → server

```json
{"kind":"command","type":"player.action","action_id":"<uuid>","hand_id":"<uuid>",
 "expected_room_version":108,"payload":{"action":"RAISE","raise_to":50}}
{"kind":"command","type":"chat.send","payload":{"body":"gg"}}   // ≤500 chars, rate limited
{"kind":"command","type":"room.sync"}   // ask for a fresh room.state
{"kind":"command","type":"ping"}        // -> pong
```

`raise_to` is the desired TOTAL street contribution (integer). Max message 8 KiB, ~10 cmd/s.
Reusing an `action_id` returns the original result (`"replayed": true`) without re-applying.

## Server → client

Envelope: `{"kind":"event","type":...,"event_id","room_id","room_version","server_time","payload"}`

| type | to | payload |
|---|---|---|
| `room.state` | everyone, after every commit | full per-recipient projection (same as `GET /rooms/{id}`) |
| `action.result` | command sender only | `{accepted:true, room_version, hand_id, action_id, replayed?}` or `{accepted:false, error:{code,message,room_version}}` |
| `hand.your_cards` | owning seat only | `{seat_no, hole_cards}` |
| `hand.started`, `blind.posted`, `hand.street_changed`, `game.action`, `chips.uncalled_refund`, `hand.showdown`, `hand.completed` | everyone | public engine events |
| `player.joined`, `player.left`, `player.sit_out`, `member.joined`, `member.kicked`, `member.banned`, `member.unbanned`, `presence` | everyone | membership / seating |
| `chip.requested`, `chip.approved`, `chip.applied`, `chip.rejected` | everyone | top-up workflow |
| `room.host_changed`, `room.config`, `room.paused`, `room.resumed`, `room.closed` | everyone | room lifecycle |
| `chat.message` | everyone (non-versioned) | `{message_id, member_id, nickname, body, created_at}` — render as text |
| `error`, `pong` | sender | malformed command / rate limit |

## Consistency rules

- Every committed state transition increments `room_version`; events are published only after
  commit, in version order (published while the room mutex is held).
- Clients must treat `room.state` as truth. On a version gap, reconnect, or mismatch, send
  `room.sync` (or `GET /rooms/{id}`) instead of applying deltas blindly.
- Presence (`connected` flags) is non-gameplay metadata and does not bump `room_version`,
  so reconnects never invalidate another player's pending action.
- Countdown: use `hand.deadline_at` with `server_time` to estimate skew; the server alone
  decides timeouts.
