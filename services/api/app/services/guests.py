"""Guest identity + DB-backed sessions (SDD §3, A-07)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.persistence.models import Guest, GuestSession
from app.security.tokens import hash_token, new_token


@dataclass
class SessionContext:
    guest: Guest
    session: GuestSession


def clean_nickname(raw: str) -> str:
    nick = " ".join(raw.split())
    nick = "".join(ch for ch in nick if ch.isprintable())
    if not 1 <= len(nick) <= 32:
        raise ValueError("nickname must be 1..32 characters")
    return nick


async def create_guest_session(
    db: AsyncSession, nickname: str, ttl: timedelta
) -> tuple[SessionContext, str]:
    guest = Guest(guest_id=uuid.uuid4(), nickname=clean_nickname(nickname))
    db.add(guest)
    await db.flush()
    ctx, token = await _issue(db, guest, ttl)
    return ctx, token


async def _issue(db: AsyncSession, guest: Guest, ttl: timedelta) -> tuple[SessionContext, str]:
    token = new_token()
    sess = GuestSession(
        id=uuid.uuid4(),
        guest_id=guest.guest_id,
        token_hash=hash_token(token),
        expires_at=datetime.now(UTC) + ttl,
    )
    db.add(sess)
    await db.flush()
    return SessionContext(guest, sess), token


async def resolve_session(db: AsyncSession, token: str | None) -> SessionContext | None:
    if not token:
        return None
    row = (
        await db.execute(
            select(GuestSession, Guest)
            .join(Guest, Guest.guest_id == GuestSession.guest_id)
            .where(GuestSession.token_hash == hash_token(token))
        )
    ).first()
    if row is None:
        return None
    sess, guest = row
    if sess.revoked_at is not None or sess.expires_at <= datetime.now(UTC):
        return None
    return SessionContext(guest, sess)


async def slide_expiry(db: AsyncSession, ctx: SessionContext, ttl: timedelta) -> None:
    """Sliding expiration: extend when less than half the TTL remains."""
    now = datetime.now(UTC)
    if ctx.session.expires_at - now < ttl / 2:
        ctx.session.expires_at = now + ttl


async def rotate_session(
    db: AsyncSession, ctx: SessionContext, ttl: timedelta
) -> tuple[SessionContext, str]:
    """Rotate token on sensitive transitions (e.g. joining a room)."""
    await db.execute(
        update(GuestSession)
        .where(GuestSession.id == ctx.session.id)
        .values(revoked_at=datetime.now(UTC))
    )
    return await _issue(db, ctx.guest, ttl)
