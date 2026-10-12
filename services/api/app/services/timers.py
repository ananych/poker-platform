"""In-process action timers. The authoritative deadline lives in PostgreSQL; a
timer wake-up only *proposes* a timeout, re-validated under the room lock (SDD §9)."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime

from app.services import clock

log = logging.getLogger("poker.timers")


class TimerService:
    def __init__(self) -> None:
        self.enabled = False
        self._tasks: dict[uuid.UUID, asyncio.Task] = {}

    def schedule(
        self, room_id: uuid.UUID, hand_id: uuid.UUID, version: int, deadline: datetime
    ) -> None:
        if not self.enabled:
            return
        self.cancel(room_id)
        self._tasks[room_id] = asyncio.create_task(
            self._run(room_id, hand_id, version, deadline), name=f"timer:{room_id}"
        )

    def cancel(self, room_id: uuid.UUID) -> None:
        task = self._tasks.pop(room_id, None)
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()

    def cancel_all(self) -> None:
        for rid in list(self._tasks):
            self.cancel(rid)

    async def _run(
        self, room_id: uuid.UUID, hand_id: uuid.UUID, version: int, deadline: datetime
    ) -> None:
        delay = (deadline - clock.now()).total_seconds()
        await asyncio.sleep(max(0.0, delay) + 0.05)
        from app.services.table import process_timeout

        try:
            await process_timeout(room_id, hand_id, version)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("timeout processing failed room=%s", room_id)


timers = TimerService()
