"""Runtime configuration (12-factor; env vars prefixed POKER_)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="POKER_", env_file=".env", extra="ignore")

    env: str = "dev"
    database_url: str = "postgresql+asyncpg://poker:poker@localhost:5432/poker"
    # 32-byte key, base64url. Envelope/data key for hole cards & deck (A-06).
    data_encryption_key: str = ""
    session_cookie_name: str = "poker_session"
    session_ttl_days: int = 30  # A-07: sliding expiration
    cookie_secure: bool = True
    allowed_origins: list[str] = ["http://localhost:3000"]
    action_timeout_seconds: int = 30
    host_disconnect_grace_seconds: int = 60
    auto_deal_delay_seconds: int = 5  # pause between hands before auto-dealing
    sit_out_stand_up_minutes: int = 10  # sitting out longer than this -> stand up + cash out
    empty_room_close_hours: int = 24
    max_chat_length: int = 500
    background_jobs: bool = True  # timers, sweeper, startup recovery
    metrics_token: str = ""  # bearer token for GET /metrics (required outside dev)
    chat_retention_days: int = 30  # A-08
    guest_sessions_per_ip_per_minute: int = 10

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalize_db_url(cls, v: str) -> str:
        """Accept plain libpq URLs (Railway/Heroku `postgres://...`, `postgresql://...`)
        and convert them for the asyncpg driver; drop libpq-only `sslmode`."""
        if not isinstance(v, str):
            return v
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                v = "postgresql+asyncpg://" + v[len(prefix) :]
        if "sslmode=" in v:
            base, _, query = v.partition("?")
            params = [p for p in query.split("&") if p and not p.startswith("sslmode=")]
            v = base + ("?" + "&".join(params) if params else "")
        return v

    @property
    def is_dev(self) -> bool:
        return self.env == "dev"


@lru_cache
def get_settings() -> Settings:
    return Settings()
