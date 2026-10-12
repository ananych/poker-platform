"""Service-layer error carrying a canonical error code (SDD §7.1)."""

from __future__ import annotations


class ServiceError(Exception):
    def __init__(self, code: str, message: str, room_version: int | None = None) -> None:
        super().__init__(message)
        self.code, self.message, self.room_version = code, message, room_version
