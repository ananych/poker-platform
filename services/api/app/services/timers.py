"""In-process timers. The authoritative deadlines live in PostgreSQL
(`hands.deadline_at`, `rooms.next_hand_at`); a wake-up only *proposes* work that is
re-validated under the room lock (SDD §9). The periodic sweeper re-checks the same
columns, so a lost or stale timer can delay but never stall a table."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime

from app.services import clock

log = logging.getLogger("poker.timers")


class TimerService:
    def __init__(self) -> None:
        self.enabled = False
        self._tasks: dict[uuid.UUID, asyncio.Task] = {}
        self._deal_tasks: dict[uuid.UUID, asyncio.Task] = {}

    # ---- action deadlines -------------------------------------------------
    def schedule(self, room_id: uuid.UUID, hand_id: uuid.UUID, deadline: datetime) -> None:
        if not self.enabled:
            return
        self.cancel(room_id)

        async def fire() -> None:
            from app.services.table import process_timeout

            await process_timeout(room_id, hand_id)

        self._tasks[room_id] = asyncio.create_task(
            self._run(deadline, fire, room_id), name=f"timer:{room_id}"
        )

    def cancel(self, room_id: uuid.UUID) -> None:
        task = self._tasks.pop(room_id, None)
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()

    # ---- auto-deal --------------------------------------------------------
    def schedule_deal(self, room_id: uuid.UUID, at: datetime) -> None:
        if not self.enabled:
            return
        old = self._deal_tasks.pop(room_id, None)
        if old is not None and old is not asyncio.current_task() and not old.done():
            old.cancel()

        async def fire() -> None:
            from app.services.table import auto_start_hand

            await auto_start_hand(room_id)

        self._deal_tasks[room_id] = asyncio.create_task(
            self._run(at, fire, room_id), name=f"deal:{room_id}"
        )

    def cancel_all(self) -> None:
        for d in (self._tasks, self._deal_tasks):
            for rid in list(d):
                t = d.pop(rid)
                if not t.done():
                    t.cancel()

    @staticmethod
    async def _run(at: datetime, fire: Callable[[], Awaitable[None]], room_id) -> None:
        delay = (at - clock.now()).total_seconds()
        await asyncio.sleep(max(0.0, delay) + 0.05)
        try:
            await fire()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("timer processing failed room=%s", room_id)


timers = TimerService()
