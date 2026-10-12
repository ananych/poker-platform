"""Per-room logical mutex (SDD §8). Valid only with a single backend worker; the
DB row lock (SELECT ... FOR UPDATE) + version check still guards other tasks."""

from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict

_locks: defaultdict[uuid.UUID, asyncio.Lock] = defaultdict(asyncio.Lock)


def room_mutex(room_id: uuid.UUID) -> asyncio.Lock:
    return _locks[room_id]


def reset() -> None:
    _locks.clear()
