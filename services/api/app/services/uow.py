"""Room unit of work (SDD §8 concurrency outline).

    acquire per-room mutex -> SELECT room FOR UPDATE -> mutate -> commit
    -> run after-commit hooks (timers) -> publish authorized projections

Publication happens while the room mutex is still held so clients observe
events in room-version order.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.poker.errors import InvariantViolation
from app.persistence.db import new_session
from app.persistence.models import Room
from app.services.errors import ServiceError
from app.services.locks import room_mutex
from app.services.metrics import metrics
from app.services.publisher import get_publisher

log = logging.getLogger("poker.uow")


@dataclass
class RoomTx:
    db: AsyncSession
    room: Room
    events: list[dict[str, Any]] = field(default_factory=list)
    changed: bool = False
    after_commit: list[Callable[[], Awaitable[None] | None]] = field(default_factory=list)
    removed_members: list[uuid.UUID] = field(default_factory=list)

    def bump(self) -> int:
        """Consume one version and produce the next (one durable transition)."""
        self.room.version += 1
        self.changed = True
        return self.room.version

    def emit(self, etype: str, payload: dict[str, Any], **extra: Any) -> None:
        self.events.append({"type": etype, "payload": payload, **extra})


@asynccontextmanager
async def room_tx(room_id: uuid.UUID) -> AsyncIterator[RoomTx]:
    async with room_mutex(room_id):
        t0 = time.perf_counter()
        try:
            async with new_session() as db:
                async with db.begin():
                    room = await db.scalar(select(Room).where(Room.id == room_id).with_for_update())
                    if room is None:
                        raise ServiceError("NOT_FOUND", "Room not found.")
                    tx = RoomTx(db, room)
                    yield tx
                # committed here
        except InvariantViolation:
            metrics.inc("invariant_failures")
            raise
        except ServiceError as e:
            metrics.inc(f"rejected.{e.code}")
            raise
        metrics.observe("room_tx", time.perf_counter() - t0)
        if tx.changed:
            for hook in tx.after_commit:
                try:
                    res = hook()
                    if res is not None:
                        await res
                except Exception:  # pragma: no cover - hooks must not break commits
                    log.exception("after-commit hook failed")
            pub = get_publisher()
            for member_id in tx.removed_members:
                await pub.member_removed(room_id, member_id)
            await pub.room_changed(room_id, tx.events)
