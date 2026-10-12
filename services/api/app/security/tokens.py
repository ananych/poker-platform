"""Opaque session / invite tokens. Only SHA-256 hashes are stored (SDD §3)."""

from __future__ import annotations

import hashlib
import hmac
import secrets


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def tokens_equal(a: bytes, b: bytes) -> bool:
    return hmac.compare_digest(a, b)
