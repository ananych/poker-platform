"""Background jobs: periodic room sweeper (host election, empty-room closure)."""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import delete, select

from app.config import get_settings
from app.persistence.db import new_session
from app.persistence.models import GuestSession, Room
from app.realtime.gateway import gateway
from app.services import chat, clock, rooms, table

log = logging.getLogger("poker.jobs")


async def sweep_once() -> None:
    async with new_session() as db:
        ids = (await db.scalars(select(Room.id).where(Room.status != "CLOSED"))).all()
    for rid in ids:
        try:
            await rooms.sweep_room(rid, gateway.connected_members(rid))
        except Exception:
            log.exception("sweep failed room=%s", rid)
    # safety nets: in-process timers are an optimization, the DB columns are truth
    for rid in await table.overdue_rooms():
        try:
            await table.process_timeout(rid)
        except Exception:
            log.exception("overdue timeout failed room=%s", rid)
    for rid in await table.due_deal_rooms():
        try:
            await table.auto_start_hand(rid)
        except Exception:
            log.exception("auto-deal failed room=%s", rid)


async def maintenance_once() -> dict:
    """A-07/A-08: purge expired sessions and chat past retention (not hands/ledger)."""
    s = get_settings()
    removed_chat = await chat.purge_expired(s.chat_retention_days)
    async with new_session() as db, db.begin():
        res = await db.execute(delete(GuestSession).where(GuestSession.expires_at < clock.now()))
    return {"chat": removed_chat, "sessions": res.rowcount or 0}


async def sweeper_loop(interval: float = 5.0, maintenance_every: float = 3600.0) -> None:
    since = 0.0
    while True:
        await asyncio.sleep(interval)
        await sweep_once()
        since += interval
        if since >= maintenance_every:
            since = 0.0
            try:
                await maintenance_once()
            except Exception:
                log.exception("maintenance failed")
