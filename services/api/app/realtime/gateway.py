"""WebSocket gateway (SDD §8).

wss://.../ws/rooms/{room_id} — authenticated by the HttpOnly session cookie plus
an Origin check; no tokens in query strings. The server (not the client) decides
connected status. After every committed mutation each connection receives the
public events it is allowed to see, then a fresh per-recipient `room.state`
projection carrying `room_version`. Private hole cards go only to the owner.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.config import get_settings
from app.persistence.db import new_session
from app.persistence.models import RoomMember
from app.security.ratelimit import RateLimiter
from app.services import chat, clock, rooms, table
from app.services.errors import ServiceError
from app.services.guests import resolve_session
from app.services.metrics import metrics
from app.services.views import load_bundle, render

log = logging.getLogger("poker.ws")

MAX_MESSAGE_BYTES = 8 * 1024
CLOSE_UNAUTHORIZED = 4401
CLOSE_FORBIDDEN = 4403


class WSLike(Protocol):
    headers: Any
    cookies: Any

    async def accept(self) -> None: ...
    async def close(self, code: int = 1000) -> None: ...
    async def send_text(self, data: str) -> None: ...
    async def receive_text(self) -> str: ...


@dataclass(eq=False)
class Connection:
    ws: WSLike
    room_id: uuid.UUID
    member_id: uuid.UUID
    guest_id: uuid.UUID
    limiter: RateLimiter = field(default_factory=lambda: RateLimiter(20, 10))
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    closed: bool = False

    async def send(self, msg: dict[str, Any]) -> bool:
        if self.closed:
            return False
        try:
            async with self.send_lock:
                await self.ws.send_text(json.dumps(msg, separators=(",", ":")))
            return True
        except Exception:
            self.closed = True
            return False


def envelope(etype: str, room_id: uuid.UUID, version: int | None, payload: Any) -> dict:
    return {
        "kind": "event",
        "type": etype,
        "event_id": str(uuid.uuid4()),
        "room_id": str(room_id),
        "room_version": version,
        "server_time": clock.now().isoformat().replace("+00:00", "Z"),
        "payload": payload,
    }


class Gateway:
    def __init__(self) -> None:
        self.conns: dict[uuid.UUID, set[Connection]] = {}

    # ---- registry -------------------------------------------------------
    def connected_members(self, room_id: uuid.UUID) -> set[uuid.UUID]:
        return {c.member_id for c in self.conns.get(room_id, ()) if not c.closed}

    def rooms_with_connections(self) -> list[uuid.UUID]:
        return [r for r, cs in self.conns.items() if cs]

    def _add(self, c: Connection) -> None:
        self.conns.setdefault(c.room_id, set()).add(c)

    def _remove(self, c: Connection) -> None:
        c.closed = True
        self.conns.get(c.room_id, set()).discard(c)

    # ---- Publisher protocol ---------------------------------------------
    async def room_changed(self, room_id: uuid.UUID, events: list[dict[str, Any]]) -> None:
        conns = [c for c in self.conns.get(room_id, ()) if not c.closed]
        if not conns:
            return
        async with new_session() as db:
            bundle = await load_bundle(db, room_id)
        if bundle is None:
            return
        members = {m.id: m for m, _ in bundle.members}
        connected = self.connected_members(room_id)
        version = bundle.room.version
        for c in conns:
            m = members.get(c.member_id)
            if m is None or m.ban_at is not None:
                await self._kick(c)
                continue
            for e in events:
                if e.get("private_to_member") not in (None, str(c.member_id)):
                    continue
                if e.get("to_member") not in (None, str(c.member_id)):
                    continue
                await c.send(envelope(e["type"], room_id, version, e["payload"]))
            ok = await c.send(
                envelope("room.state", room_id, version, render(bundle, m, connected))
            )
            if not ok:
                self._remove(c)

    async def broadcast(self, room_id: uuid.UUID, etype: str, payload: Any) -> None:
        """Non-versioned broadcast (chat)."""
        for c in [c for c in self.conns.get(room_id, ()) if not c.closed]:
            if not await c.send(envelope(etype, room_id, None, payload)):
                self._remove(c)

    def gauges(self) -> dict[str, int]:
        live = {r: [c for c in cs if not c.closed] for r, cs in self.conns.items()}
        return {
            "ws_connections": sum(len(v) for v in live.values()),
            "rooms_with_connections": sum(1 for v in live.values() if v),
        }

    async def close_all(self, code: int = 1012) -> None:
        """Deploy/restart: tell clients to reconnect (1012 = service restart)."""
        for cs in list(self.conns.values()):
            for c in list(cs):
                self._remove(c)
                try:
                    await c.ws.close(code=code)
                except Exception:
                    pass

    async def member_removed(self, room_id: uuid.UUID, member_id: uuid.UUID) -> None:
        for c in list(self.conns.get(room_id, ())):
            if c.member_id == member_id:
                await self._kick(c)

    async def _kick(self, c: Connection) -> None:
        self._remove(c)
        try:
            await c.ws.close(code=CLOSE_FORBIDDEN)
        except Exception:
            pass

    async def send_state(self, c: Connection) -> None:
        async with new_session() as db:
            bundle = await load_bundle(db, c.room_id)
            member = await db.get(RoomMember, c.member_id)
        if bundle is None or member is None:
            return
        await c.send(
            envelope(
                "room.state",
                c.room_id,
                bundle.room.version,
                render(bundle, member, self.connected_members(c.room_id)),
            )
        )

    # ---- connection lifecycle -------------------------------------------
    async def handle(self, ws: WSLike, room_id: uuid.UUID) -> None:
        s = get_settings()
        origin = ws.headers.get("origin")
        if origin is not None and origin not in s.allowed_origins:
            await ws.close(code=CLOSE_FORBIDDEN)
            return
        async with new_session() as db:
            ctx = await resolve_session(db, ws.cookies.get(s.session_cookie_name))
            member = None
            if ctx is not None:
                try:
                    member = await table.member_of(db, room_id, ctx.guest.guest_id)
                except ServiceError:
                    member = None
        if ctx is None:
            await ws.close(code=CLOSE_UNAUTHORIZED)
            return
        if member is None:
            await ws.close(code=CLOSE_FORBIDDEN)
            return

        await ws.accept()
        metrics.inc("ws_connects")
        conn = Connection(ws, room_id, member.id, ctx.guest.guest_id)
        self._add(conn)
        try:
            await rooms.on_connect(room_id, member.id, self.connected_members(room_id))
            while not conn.closed:
                raw = await ws.receive_text()
                await self._on_message(conn, raw)
        except Exception as e:  # disconnect or transport error
            if type(e).__name__ not in ("WebSocketDisconnect", "ClientDisconnected"):
                log.debug("ws closed: %r", e)
        finally:
            metrics.inc("ws_disconnects")
            self._remove(conn)
            try:
                await rooms.on_disconnect(room_id, member.id, self.connected_members(room_id))
            except Exception:
                log.exception("presence update failed")

    async def _on_message(self, c: Connection, raw: str) -> None:
        def err(code: str, message: str, version: int | None = None, **extra: Any) -> dict:
            return envelope(
                "error", c.room_id, version, {"code": code, "message": message, **extra}
            )

        if len(raw.encode()) > MAX_MESSAGE_BYTES:
            await c.send(err("VALIDATION_ERROR", "Message too large."))
            return
        if not c.limiter.allow("cmd"):
            await c.send(err("RATE_LIMITED", "Slow down."))
            return
        try:
            msg = json.loads(raw)
            assert isinstance(msg, dict) and msg.get("kind") == "command"
            mtype = msg["type"]
        except Exception:
            await c.send(err("VALIDATION_ERROR", "Malformed command."))
            return

        if mtype == "ping":
            await c.send(envelope("pong", c.room_id, None, {}))
        elif mtype == "room.sync":
            await self.send_state(c)
        elif mtype == "chat.send":
            try:
                body = (msg.get("payload") or {}).get("body")
                if not isinstance(body, str):
                    raise ServiceError("VALIDATION_ERROR", "body must be text.")
                out = await chat.post_message(c.room_id, c.guest_id, body)
                await self.broadcast(c.room_id, "chat.message", out)
            except ServiceError as e:
                await c.send(err(e.code, e.message))
        elif mtype == "player.action":
            action_id = msg.get("action_id")
            try:
                payload = msg.get("payload") or {}
                raise_to = payload.get("raise_to")
                if raise_to is not None and (
                    not isinstance(raise_to, int) or isinstance(raise_to, bool)
                ):
                    raise ServiceError("INVALID_ACTION", "raise_to must be an integer.")
                with metrics.timer("ws_action_roundtrip"):
                    result = await table.player_action(
                        c.room_id,
                        c.guest_id,
                        action_id=uuid.UUID(str(action_id)),
                        hand_id=uuid.UUID(str(msg["hand_id"])),
                        expected_version=int(msg["expected_room_version"]),
                        action=str(payload.get("action")),
                        raise_to=raise_to,
                    )
                await c.send(
                    envelope(
                        "action.result",
                        c.room_id,
                        result["room_version"],
                        {**result, "action_id": str(action_id)},
                    )
                )
            except ServiceError as e:
                await c.send(
                    envelope(
                        "action.result",
                        c.room_id,
                        e.room_version,
                        {
                            "accepted": False,
                            "action_id": str(action_id),
                            "error": {
                                "code": e.code,
                                "message": e.message,
                                "room_version": e.room_version,
                            },
                        },
                    )
                )
                if e.code == "ROOM_BANNED":
                    await self._kick(c)
            except (KeyError, ValueError, TypeError):
                await c.send(err("VALIDATION_ERROR", "Invalid action command."))
        else:
            await c.send(err("VALIDATION_ERROR", f"Unknown command {mtype!r}."))


gateway = Gateway()
