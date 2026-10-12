"""Data-encryption key provider (A-06)."""

from __future__ import annotations

import logging
from functools import lru_cache

from app.config import get_settings
from app.security.crypto import Cipher

log = logging.getLogger("poker.secrets")


@lru_cache
def get_cipher() -> Cipher:
    s = get_settings()
    if s.data_encryption_key:
        return Cipher(s.data_encryption_key)
    if s.env in ("dev", "test"):
        log.warning(
            "POKER_DATA_ENCRYPTION_KEY not set; using an EPHEMERAL key (dev/test only). "
            "Live hands cannot be recovered after restart."
        )
        return Cipher(Cipher.generate_key())
    raise RuntimeError("POKER_DATA_ENCRYPTION_KEY is required outside dev/test")
