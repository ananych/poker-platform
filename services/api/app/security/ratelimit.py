"""In-process token-bucket rate limiter (single always-on instance, SDD §1)."""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class _Bucket:
    tokens: float
    updated: float


class RateLimiter:
    def __init__(self, capacity: int, refill_per_sec: float) -> None:
        self.capacity, self.refill = capacity, refill_per_sec
        self._b: dict[str, _Bucket] = {}

    def _bucket(self, key: str, now: float | None) -> _Bucket:
        now = time.monotonic() if now is None else now
        b = self._b.get(key) or _Bucket(self.capacity, now)
        b.tokens = min(self.capacity, b.tokens + (now - b.updated) * self.refill)
        b.updated = now
        self._b[key] = b
        return b

    def allow(self, key: str, now: float | None = None) -> bool:
        """Consume one token if available."""
        b = self._bucket(key, now)
        if b.tokens >= 1:
            b.tokens -= 1
            return True
        return False

    def blocked(self, key: str, now: float | None = None) -> bool:
        """True when no token is left (does not consume)."""
        return self._bucket(key, now).tokens < 1

    def penalize(self, key: str, now: float | None = None) -> None:
        """Consume a token for a failed attempt (failure-only limiting)."""
        b = self._bucket(key, now)
        b.tokens = max(0.0, b.tokens - 1)

    def reset(self) -> None:
        self._b.clear()


def _guest_limit() -> int:
    from app.config import get_settings

    return get_settings().guest_sessions_per_ip_per_minute


guest_create_limiter = RateLimiter(capacity=_guest_limit(), refill_per_sec=_guest_limit() / 60)
password_guess_limiter = RateLimiter(capacity=5, refill_per_sec=5 / 300)
chat_limiter = RateLimiter(capacity=5, refill_per_sec=1)
