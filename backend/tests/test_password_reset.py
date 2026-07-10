"""Password-reset flow: forgot → reset happy path + guards.

Uses the console email provider to extract the code from logs.
"""
from __future__ import annotations

import logging

import pytest

from .conftest import register_user


pytestmark = pytest.mark.asyncio


def _extract_code(caplog, marker: str = "password reset code is:") -> str:
    for rec in caplog.records:
        msg = rec.getMessage()
        if marker in msg:
            after = msg.split(marker)[1].strip()
            return after.split()[0]
    raise AssertionError(f"no code found in logs; got: {[r.getMessage()[:80] for r in caplog.records]}")


async def test_forgot_password_returns_204_and_sends_code(client, caplog):
    user = await register_user(client)
    with caplog.at_level(logging.WARNING, logger="app.services.email_service"):
        r = await client.post(
            "/api/auth/password/forgot",
            json={"email": user["email"]},
        )
    assert r.status_code == 204, r.text
    code = _extract_code(caplog)
    assert len(code) == 6 and code.isdigit()


async def test_forgot_password_unknown_email_still_204(client, caplog):
    """Anti-enumeration: unknown email returns the same 204 as a real one."""
    with caplog.at_level(logging.WARNING, logger="app.services.email_service"):
        r = await client.post(
            "/api/auth/password/forgot",
            json={"email": "ghost@example.com"},
        )
    assert r.status_code == 204
    # No code should have been generated.
    assert not any(
        "password reset code is:" in rec.getMessage() for rec in caplog.records
    )


async def test_reset_password_with_correct_code_replaces_hash(client, caplog):
    user = await register_user(client)
    with caplog.at_level(logging.WARNING, logger="app.services.email_service"):
        await client.post("/api/auth/password/forgot", json={"email": user["email"]})
        code = _extract_code(caplog)

    r = await client.post(
        "/api/auth/password/reset",
        json={
            "email": user["email"],
            "code": code,
            "password": "brand-new-password-9",
        },
    )
    assert r.status_code == 204, r.text

    # Old password must fail.
    r = await client.post(
        "/api/auth/login",
        json={"email": user["email"], "password": user["password"]},
    )
    assert r.status_code == 401

    # New password works.
    r = await client.post(
        "/api/auth/login",
        json={"email": user["email"], "password": "brand-new-password-9"},
    )
    assert r.status_code == 200


async def test_reset_password_wrong_code_decrements_and_locks(client, caplog):
    user = await register_user(client)
    with caplog.at_level(logging.WARNING, logger="app.services.email_service"):
        await client.post("/api/auth/password/forgot", json={"email": user["email"]})
        _extract_code(caplog)  # sanity

    for _ in range(4):
        r = await client.post(
            "/api/auth/password/reset",
            json={"email": user["email"], "code": "000000", "password": "irrelevant"},
        )
        # First rejects on the CODE (mismatched), not the password.
        assert r.status_code == 400
        assert r.json()["detail"]["code"] == "CODE_INVALID"

    r = await client.post(
        "/api/auth/password/reset",
        json={"email": user["email"], "code": "000000", "password": "irrelevant"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "CODE_EXHAUSTED"


async def test_reset_password_revokes_outstanding_refresh_tokens(client, caplog):
    """After reset, previously issued refresh tokens must be dead."""
    user = await register_user(client)
    # After register, client.cookies has a refresh + csrf pair.
    original_refresh = client.cookies.get("refresh")
    csrf = client.cookies.get("csrf")
    assert original_refresh and csrf

    with caplog.at_level(logging.WARNING, logger="app.services.email_service"):
        await client.post("/api/auth/password/forgot", json={"email": user["email"]})
        code = _extract_code(caplog)

    r = await client.post(
        "/api/auth/password/reset",
        json={"email": user["email"], "code": code, "password": "another-new-pw-9"},
    )
    assert r.status_code == 204

    # The old refresh token must no longer work.
    r2 = await client.post(
        "/api/auth/refresh",
        headers={
            "X-CSRF-Token": csrf,
            "Cookie": f"refresh={original_refresh}; csrf={csrf}",
        },
    )
    assert r2.status_code == 401


async def test_reset_password_short_password_rejected(client, caplog):
    """Server-side minimum length still enforced even with a valid code."""
    user = await register_user(client)
    with caplog.at_level(logging.WARNING, logger="app.services.email_service"):
        await client.post("/api/auth/password/forgot", json={"email": user["email"]})
        code = _extract_code(caplog)
    r = await client.post(
        "/api/auth/password/reset",
        json={"email": user["email"], "code": code, "password": "short"},
    )
    # Pydantic schema-level validation (Field min_length=8) catches this before
    # the service ever sees it.
    assert r.status_code == 422
