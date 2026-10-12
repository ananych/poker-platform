"""Auth dependencies: cookie session → guest. Never trust client-reported IDs."""

from __future__ import annotations

from datetime import timedelta

from fastapi import Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.config import Settings, get_settings
from app.persistence.db import get_session
from app.services.guests import SessionContext, resolve_session, slide_expiry


def set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=int(timedelta(days=settings.session_ttl_days).total_seconds()),
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


async def optional_session(
    request: Request,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> SessionContext | None:
    return await resolve_session(db, request.cookies.get(settings.session_cookie_name))


async def require_session(
    request: Request,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> SessionContext:
    ctx = await resolve_session(db, request.cookies.get(settings.session_cookie_name))
    if ctx is None:
        raise ApiError("UNAUTHORIZED", "A valid guest session is required.")
    await slide_expiry(db, ctx, timedelta(days=settings.session_ttl_days))
    await db.commit()
    return ctx
