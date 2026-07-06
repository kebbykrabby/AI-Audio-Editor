"""Email-verification integration tests.

Covers the request/verify flow + the export gate. Uses the console email
provider (default) and captures the emitted code from logs.
"""
from __future__ import annotations

import logging

import pytest

from .conftest import register_user


pytestmark = pytest.mark.asyncio


def _extract_code(caplog: pytest.LogCaptureFixture) -> str:
    """The ConsoleEmailProvider logs the body containing 'Your verification
    code is: NNNNNN'. Pull the six digits out."""
    for rec in caplog.records:
        msg = rec.getMessage()
        if "Your verification code is:" in msg:
            after = msg.split("Your verification code is:")[1].strip()
            return after.split()[0]
    raise AssertionError(f"no verification code found in logs; got: {[r.getMessage()[:80] for r in caplog.records]}")


# --- request + verify happy path ------------------------------------------

async def test_request_and_verify_email_success(client, caplog):
    user = await register_user(client, verify_email=False)
    # Freshly registered password-signup user: unverified.
    r_me = await client.get("/api/auth/me", headers=user["headers"])
    assert r_me.status_code == 200
    assert r_me.json()["emailVerified"] is False

    with caplog.at_level(logging.WARNING, logger="app.services.email_service"):
        r = await client.post("/api/auth/email/request-verify", headers=user["headers"])
        assert r.status_code == 204, r.text
        code = _extract_code(caplog)

    r2 = await client.post(
        "/api/auth/email/verify",
        json={"code": code},
        headers=user["headers"],
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["emailVerified"] is True


async def test_verify_with_wrong_code_decrements_and_locks_after_max(client, caplog):
    user = await register_user(client, verify_email=False)
    with caplog.at_level(logging.WARNING, logger="app.services.email_service"):
        r = await client.post("/api/auth/email/request-verify", headers=user["headers"])
        assert r.status_code == 204
        _extract_code(caplog)  # sanity — a code was issued

    # Default EMAIL_VERIFY_MAX_ATTEMPTS=5; burn them all with wrong codes.
    for i in range(4):
        r = await client.post(
            "/api/auth/email/verify",
            json={"code": "000000"},
            headers=user["headers"],
        )
        assert r.status_code == 400
        assert r.json()["detail"]["code"] == "CODE_INVALID", i

    # 5th wrong attempt: exhaust.
    r = await client.post(
        "/api/auth/email/verify",
        json={"code": "000000"},
        headers=user["headers"],
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "CODE_EXHAUSTED"

    # Even the (still-unknown-to-attacker) correct code shouldn't work now.
    r = await client.post(
        "/api/auth/email/verify",
        json={"code": "111111"},
        headers=user["headers"],
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "CODE_EXPIRED_OR_MISSING"


async def test_new_request_invalidates_previous_code(client, caplog):
    user = await register_user(client, email="rotate@example.com", verify_email=False)

    with caplog.at_level(logging.WARNING, logger="app.services.email_service"):
        r = await client.post("/api/auth/email/request-verify", headers=user["headers"])
        assert r.status_code == 204
        first_code = _extract_code(caplog)

    caplog.clear()

    # Bypass the per-minute rate limit for this test.
    from app.config import settings
    settings.EMAIL_VERIFY_RATE_PER_MIN = 999

    with caplog.at_level(logging.WARNING, logger="app.services.email_service"):
        r = await client.post("/api/auth/email/request-verify", headers=user["headers"])
        assert r.status_code == 204
        second_code = _extract_code(caplog)

    assert first_code != second_code, "regenerated code should differ (odds astronomical)"

    # First code must no longer work — it was invalidated.
    r = await client.post(
        "/api/auth/email/verify",
        json={"code": first_code},
        headers=user["headers"],
    )
    # Two acceptable failure modes: treated as invalid-for-current-row, or
    # collapsed to expired/missing when the invalidated row is skipped.
    assert r.status_code == 400
    assert r.json()["detail"]["code"] in ("CODE_INVALID", "CODE_EXPIRED_OR_MISSING")

    # Second (current) code works.
    r = await client.post(
        "/api/auth/email/verify",
        json={"code": second_code},
        headers=user["headers"],
    )
    assert r.status_code == 200


async def test_request_verify_rate_limited_per_minute(client, caplog):
    user = await register_user(client, verify_email=False)

    from app.config import settings
    settings.EMAIL_VERIFY_RATE_PER_MIN = 1

    with caplog.at_level(logging.WARNING, logger="app.services.email_service"):
        r = await client.post("/api/auth/email/request-verify", headers=user["headers"])
        assert r.status_code == 204

    # Immediate second request within the same minute → 429.
    r2 = await client.post("/api/auth/email/request-verify", headers=user["headers"])
    assert r2.status_code == 429
    assert r2.json()["detail"]["code"] == "EMAIL_VERIFY_RATE_LIMITED"


async def test_request_verify_rejects_already_verified(client, caplog):
    user = await register_user(client, verify_email=False)
    with caplog.at_level(logging.WARNING, logger="app.services.email_service"):
        r = await client.post("/api/auth/email/request-verify", headers=user["headers"])
        code = _extract_code(caplog)
    r2 = await client.post(
        "/api/auth/email/verify",
        json={"code": code},
        headers=user["headers"],
    )
    assert r2.status_code == 200

    # Now verified — a fresh request-verify should 409.
    from app.config import settings
    settings.EMAIL_VERIFY_RATE_PER_MIN = 999  # ensure it's the "already verified" path, not rate limit

    r3 = await client.post("/api/auth/email/request-verify", headers=user["headers"])
    assert r3.status_code == 409
    assert r3.json()["detail"]["code"] == "EMAIL_ALREADY_VERIFIED"


# --- Export gate ----------------------------------------------------------

async def test_export_blocked_until_email_verified(client, caplog, monkeypatch):
    """The export endpoint returns 403 EMAIL_VERIFICATION_REQUIRED until the
    user verifies. Bypass the actual export enqueue by mocking asset lookup.
    """
    from app.services import export_service

    async def _boom(*args, **kwargs):
        # If we get past the gate, this signals the wrong path — the gate
        # should have short-circuited before enqueue_export runs.
        raise AssertionError("email verification gate should have blocked this call")

    monkeypatch.setattr(export_service, "enqueue_export", _boom)

    user = await register_user(client, verify_email=False)
    r = await client.post(
        "/api/assets/some-asset-id/export",
        json={"format": "wav"},
        headers=user["headers"],
    )
    assert r.status_code == 403, r.text
    assert r.json()["error"]["code"] == "EMAIL_VERIFICATION_REQUIRED"


async def test_export_allowed_after_email_verified(client, caplog, monkeypatch):
    """Once verified, the export API proceeds past the gate. We mock the
    downstream enqueue so we don't need a real asset row."""
    from app.models.export import Export
    from app.services import export_service

    async def _fake_enqueue(db, *, user, asset_id, fmt, sample_rate, bitrate_kbps):
        return Export(
            id="exp-fake",
            user_id=user.id,
            source_asset_id=asset_id,
            status="queued",
            format=fmt,
            sample_rate=sample_rate,
            bitrate_kbps=bitrate_kbps,
        )

    monkeypatch.setattr(export_service, "enqueue_export", _fake_enqueue)

    user = await register_user(client, verify_email=False)
    with caplog.at_level(logging.WARNING, logger="app.services.email_service"):
        r = await client.post("/api/auth/email/request-verify", headers=user["headers"])
        code = _extract_code(caplog)
    r2 = await client.post(
        "/api/auth/email/verify",
        json={"code": code},
        headers=user["headers"],
    )
    assert r2.status_code == 200

    r3 = await client.post(
        "/api/assets/some-asset-id/export",
        json={"format": "wav"},
        headers=user["headers"],
    )
    assert r3.status_code == 202, r3.text
    assert r3.json()["exportId"] == "exp-fake"


async def test_export_allowed_for_oauth_user_without_flow(client, monkeypatch):
    """OAuth users with a provider-verified email must not hit the gate.
    Simulate this by creating a user directly and stamping email_verified_at.
    """
    from datetime import datetime

    from app.database import async_session
    from app.models.export import Export
    from app.models.user import User
    from app.services import export_service

    async def _fake_enqueue(db, *, user, asset_id, fmt, sample_rate, bitrate_kbps):
        return Export(
            id="exp-oauth",
            user_id=user.id,
            source_asset_id=asset_id,
            status="queued",
            format=fmt,
            sample_rate=sample_rate,
            bitrate_kbps=bitrate_kbps,
        )

    monkeypatch.setattr(export_service, "enqueue_export", _fake_enqueue)

    # Register first so a user row + token exist, then stamp email_verified_at.
    user = await register_user(client, verify_email=False)
    async with async_session() as db:
        u = await db.get(User, user["userId"])
        u.email_verified_at = datetime.utcnow()
        await db.commit()

    r = await client.post(
        "/api/assets/some-asset-id/export",
        json={"format": "wav"},
        headers=user["headers"],
    )
    assert r.status_code == 202, r.text
