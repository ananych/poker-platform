import pytest
from cryptography.exceptions import InvalidTag

from app.security.crypto import Cipher
from app.security.passwords import hash_password, verify_password
from app.security.ratelimit import RateLimiter
from app.security.tokens import hash_token, new_token


def test_argon2id_roundtrip():
    h = hash_password("hunter22")
    assert h.startswith("$argon2id$") and "hunter22" not in h
    assert verify_password(h, "hunter22")
    assert not verify_password(h, "wrong")
    assert not verify_password("garbage", "x")


def test_token_hash_is_stable_and_opaque():
    t = new_token()
    assert len(t) >= 43 and hash_token(t) == hash_token(t) and len(hash_token(t)) == 32


def test_cipher_roundtrip_and_aad_binding():
    c = Cipher(Cipher.generate_key())
    blob = c.encrypt_json({"hole": ["Ah", "Kd"]}, aad=b"hand-1")
    assert b"Ah" not in blob
    assert c.decrypt_json(blob, aad=b"hand-1") == {"hole": ["Ah", "Kd"]}
    with pytest.raises(InvalidTag):
        c.decrypt(blob, aad=b"hand-2")


def test_rate_limiter():
    rl = RateLimiter(capacity=2, refill_per_sec=1)
    assert rl.allow("k", 0) and rl.allow("k", 0) and not rl.allow("k", 0)
    assert rl.allow("k", 1.0)
