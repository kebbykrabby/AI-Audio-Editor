"""Pure-function auth tests: password hashing, JWT, opaque tokens, code generator.

No DB, no HTTP — these cover the primitives in app.core.security.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import jwt
import pytest

# NB: importing app.core.security pulls in Settings, so conftest's env setup runs.
from app.core import security


def test_password_hash_and_verify_roundtrip():
    h = security.hash_password("correct-horse-battery-staple")
    assert h != "correct-horse-battery-staple"
    assert h.startswith("$argon2")
    assert security.verify_password("correct-horse-battery-staple", h) is True
    assert security.verify_password("wrong-password", h) is False


def test_password_hash_is_salted_not_deterministic():
    h1 = security.hash_password("same-input")
    h2 = security.hash_password("same-input")
    assert h1 != h2, "argon2 should salt; identical inputs must hash differently"
    assert security.verify_password("same-input", h1)
    assert security.verify_password("same-input", h2)


def test_access_token_roundtrip():
    token = security.encode_access_token("user-123")
    payload = security.decode_access_token(token)
    assert payload["sub"] == "user-123"
    assert payload["typ"] == "access"
    assert "iat" in payload and "exp" in payload


def test_access_token_expired_rejected():
    # Issue a token with an immediate expiry and wait a moment past it.
    token = security.encode_access_token("user-123", ttl_min=0)
    # ttl_min=0 → iat == exp; jwt.decode uses strict comparison, expired.
    time.sleep(1)
    with pytest.raises(jwt.ExpiredSignatureError):
        security.decode_access_token(token)


def test_access_token_wrong_typ_rejected():
    # Mint a token with a different typ — simulates a refresh or state token
    # being smuggled in as an access token.
    from app.config import settings
    now = datetime.now(timezone.utc)
    bad = jwt.encode(
        {
            "sub": "user-123",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
            "typ": "refresh",
        },
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    with pytest.raises(jwt.InvalidTokenError):
        security.decode_access_token(bad)


def test_opaque_token_and_sha256_hash_are_deterministic_per_input():
    token = security.generate_opaque_token()
    assert len(token) >= 32, "opaque token should be long enough to resist guessing"

    h1 = security.sha256_bytes(token)
    h2 = security.sha256_bytes(token)
    assert h1 == h2, "sha256 should be deterministic for the same input"
    assert len(h1) == 32  # 256 bits

    other = security.generate_opaque_token()
    assert other != token
    assert security.sha256_bytes(other) != h1


def test_state_token_roundtrip_and_payload_preserved():
    token = security.encode_state_token({"prov": "google", "nonce": "abc123"})
    payload = security.decode_state_token(token)
    assert payload["prov"] == "google"
    assert payload["nonce"] == "abc123"
    assert "exp" in payload


def test_otp_code_is_six_digits():
    seen = set()
    for _ in range(50):
        code = security.generate_otp_code()
        assert len(code) == 6
        assert code.isdigit()
        seen.add(code)
    # Very weak randomness check; primarily guards against "always 000000".
    assert len(seen) > 10, "OTP generator looks non-random"
