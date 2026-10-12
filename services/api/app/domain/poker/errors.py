"""Domain errors carry canonical error codes (SDD §7.1)."""

from __future__ import annotations


class EngineError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class InvariantViolation(AssertionError):
    """Raised when a state breaks a conservation / uniqueness invariant."""
