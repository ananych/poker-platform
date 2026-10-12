"""AES-256-GCM encryption for private hand data at rest (hole cards, deck).

A-06: key comes from the cloud secrets manager via POKER_DATA_ENCRYPTION_KEY.
Ciphertext layout: key_id(1) | nonce(12) | ciphertext+tag. Associated data binds
ciphertext to its row (e.g. hand_id) so blobs cannot be swapped between rows.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_ID = 1


class Cipher:
    def __init__(self, key_b64: str) -> None:
        key = base64.urlsafe_b64decode(key_b64 + "=" * (-len(key_b64) % 4))
        if len(key) != 32:
            raise ValueError("data encryption key must be 32 bytes (base64url)")
        self._aead = AESGCM(key)

    @staticmethod
    def generate_key() -> str:
        return base64.urlsafe_b64encode(AESGCM.generate_key(bit_length=256)).decode().rstrip("=")

    def encrypt(self, plaintext: bytes, aad: bytes = b"") -> bytes:
        nonce = os.urandom(12)
        return bytes([KEY_ID]) + nonce + self._aead.encrypt(nonce, plaintext, aad)

    def decrypt(self, blob: bytes, aad: bytes = b"") -> bytes:
        if not blob or blob[0] != KEY_ID:
            raise ValueError("unknown key id")
        return self._aead.decrypt(blob[1:13], blob[13:], aad)

    def encrypt_json(self, obj: Any, aad: bytes = b"") -> bytes:
        return self.encrypt(json.dumps(obj, separators=(",", ":")).encode(), aad)

    def decrypt_json(self, blob: bytes, aad: bytes = b"") -> Any:
        return json.loads(self.decrypt(blob, aad))
