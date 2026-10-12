"""REST: POST /guests/session, GET /me (SDD §7)."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import optional_session, require_session, set_session_cookie
from app.api.errors import ApiError
from app.config import Settings, get_settings
from app.persistence.db import get_session
from app.security.ratelimit import guest_create_limiter
from app.services.guests import SessionContext, clean_nickname, create_guest_session
from app.services.rooms import my_rooms

router = APIRouter()


class GuestIn(BaseModel):
    nickname: str = Field(min_length=1, max_length=64)


class GuestOut(BaseModel):
    guest_id: str
    nickname: str


class MeOut(GuestOut):
    rooms: list[dict] = []


@router.post("/guests/session", response_model=GuestOut)
async def create_or_resume(
    body: GuestIn,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    existing: SessionContext | None = Depends(optional_session),
):
    try:
        nick = clean_nickname(body.nickname)
    except ValueError as e:
        raise ApiError("VALIDATION_ERROR", str(e)) from None
    if existing is not None:  # resume: nickname is display-only and may change
        existing.guest.nickname = nick
        await db.commit()
        return GuestOut(guest_id=str(existing.guest.guest_id), nickname=nick)
    client = request.client.host if request.client else "unknown"
    if not guest_create_limiter.allow(client):
        raise ApiError("RATE_LIMITED", "Too many new sessions; slow down.")
    ctx, token = await create_guest_session(db, nick, timedelta(days=settings.session_ttl_days))
    await db.commit()
    set_session_cookie(response, token, settings)
    return GuestOut(guest_id=str(ctx.guest.guest_id), nickname=ctx.guest.nickname)


@router.get("/me", response_model=MeOut)
async def me(ctx: SessionContext = Depends(require_session)):
    return MeOut(
        guest_id=str(ctx.guest.guest_id),
        nickname=ctx.guest.nickname,
        rooms=await my_rooms(ctx.guest.guest_id),
    )
