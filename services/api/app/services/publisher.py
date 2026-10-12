"""Post-commit publication hook. Services call it only AFTER a transaction commits;
the realtime gateway registers the concrete implementation."""

from __future__ import annotations

import uuid
from typing import Any, Protocol


class Publisher(Protocol):
    async def room_changed(self, room_id: uuid.UUID, events: list[dict[str, Any]]) -> None: ...

    async def member_removed(self, room_id: uuid.UUID, member_id: uuid.UUID) -> None: ...


class NullPublisher:
    async def room_changed(self, room_id: uuid.UUID, events: list[dict[str, Any]]) -> None:
        return None

    async def member_removed(self, room_id: uuid.UUID, member_id: uuid.UUID) -> None:
        return None


_publisher: Publisher = NullPublisher()


def get_publisher() -> Publisher:
    return _publisher


def set_publisher(p: Publisher) -> None:
    global _publisher
    _publisher = p
