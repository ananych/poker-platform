"""Room password hashing with Argon2id (SDD §3, §12)."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_ph = PasswordHasher()  # argon2id defaults


def hash_password(password: str) -> str:
    if not 4 <= len(password) <= 128:
        raise ValueError("password length must be 4..128")
    return _ph.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
