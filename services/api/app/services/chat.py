"""Room text chat (SDD §2): members only, sanitized, rate limited, non-versioned."""

from __future__ import annotations

import re
import unicodedata
import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete, select

from app.config import get_settings
from app.persistence.db import new_session
from app.persistence.models import ChatMessage, Guest, Room, RoomMember
from app.security.ratelimit import chat_limiter
from app.services import clock
from app.services.errors import ServiceError
from app.services.table import member_of

MAX_NEWLINES = 4


def sanitize(raw: str) -> str:
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(ch for ch in text if ch == "\n" or not unicodedata.category(ch).startswith("C"))
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text).strip()
    if text.count("\n") > MAX_NEWLINES:
        head = text.split("\n")
        text = "\n".join(head[:MAX_NEWLINES]) + " " + " ".join(head[MAX_NEWLINES:])
    limit = get_settings().max_chat_length
    if not text:
        raise ServiceError("VALIDATION_ERROR", "Message is empty.")
    if len(text) > limit:
        raise ServiceError("VALIDATION_ERROR", f"Message longer than {limit} characters.")
    return text


def _out(msg: ChatMessage, nickname: str | None) -> dict:
    return {
        "message_id": str(msg.id),
        "member_id": str(msg.member_id),
        "nickname": nickname,
        "body": msg.body,
        "created_at": msg.created_at.isoformat(),
    }


async def post_message(room_id: uuid.UUID, guest_id: uuid.UUID, body: str) -> dict:
    text = sanitize(body or "")
    async with new_session() as db, db.begin():
        member = await member_of(db, room_id, guest_id)
        status = await db.scalar(select(Room.status).where(Room.id == room_id))
        if status == "CLOSED":
            raise ServiceError("ROOM_CLOSED", "Room is closed.")
        if not chat_limiter.allow(str(member.id)):
            raise ServiceError("RATE_LIMITED", "You are sending messages too fast.")
        msg = ChatMessage(
            id=uuid.uuid4(), room_id=room_id, member_id=member.id, body=text, created_at=clock.now()
        )
        db.add(msg)
        nick = await db.scalar(select(Guest.nickname).where(Guest.guest_id == guest_id))
        await db.flush()
        return _out(msg, nick)


async def recent(
    room_id: uuid.UUID, guest_id: uuid.UUID, *, before: datetime | None = None, limit: int = 50
) -> list[dict]:
    limit = max(1, min(limit, 100))
    async with new_session() as db:
        await member_of(db, room_id, guest_id)
        q = (
            select(ChatMessage, Guest.nickname)
            .join(RoomMember, RoomMember.id == ChatMessage.member_id)
            .join(Guest, Guest.guest_id == RoomMember.guest_id)
            .where(ChatMessage.room_id == room_id)
        )
        if before is not None:
            q = q.where(ChatMessage.created_at < before)
        rows = (await db.execute(q.order_by(ChatMessage.created_at.desc()).limit(limit))).all()
        return [_out(m, n) for m, n in reversed(rows)]


async def purge_expired(retention_days: int) -> int:
    """A-08: chat retention is independent from hand/ledger records."""
    cutoff = clock.now() - timedelta(days=retention_days)
    async with new_session() as db, db.begin():
        res = await db.execute(delete(ChatMessage).where(ChatMessage.created_at < cutoff))
        return res.rowcount or 0
