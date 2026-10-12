"""Server UTC clock (authoritative for deadlines, SDD §12). Overridable in tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

_offset = timedelta(0)


def now() -> datetime:
    return datetime.now(UTC) + _offset


def advance(delta: timedelta) -> None:
    """Test helper: move the server clock forward."""
    global _offset
    _offset += delta


def reset() -> None:
    global _offset
    _offset = timedelta(0)
