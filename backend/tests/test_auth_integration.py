"""Auth integration tests: register, login, refresh, logout, OTP, OAuth.

Exercises the HTTP surface end-to-end against the in-process app + StubBroker.
"""
from __future__ import annotations

import secrets

import pytest

from .conftest import register_user


pytestmark = pytest.mark.asyncio


# --- Register / login / me ------------------------------------------------

async def test_register_returns_access_token_and_cookies(client):
    email = f"reg-{secrets.token_hex(4)}@example.com"
    r = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "display_name": "Reggie"},
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["accessToken"]
    assert data["user"]["email"] == email
    # Cookies set on the response — httpx persists them into client.cookies
    assert client.cookies.get("refresh")
    assert client.cookies.get("csrf")


async def test_login_wrong_password_returns_generic_401(client):
    email = f"wp-{secrets.token_hex(4)}@example.com"
    await register_user(client, email=email, password="correct-password-12345")
    # Wrong password for a known email
    r = await client.post(
        "/api/auth/login",
        json={"email": email, "password": "definitely-not-right"},
    )
    assert r.status_code == 401
    # Unknown email (must produce the same response shape — no enumeration)
    r2 = await client.post(
        "/api/auth/login",
        json={"email": "ghost-no-such-user@example.com", "password": "anything-at-all"},
    )
    assert r2.status_code == 401
    assert r.json()["detail"]["code"] == r2.json()["detail"]["code"] == "INVALID_CREDENTIALS"


async def test_me_requires_bearer(client):
    r = await client.get("/api/auth/me")
    assert r.status_code == 401

    user = await register_user(client)
    r2 = await client.get("/api/auth/me", headers=user["headers"])
    assert r2.status_code == 200
    assert r2.json()["userId"] == user["userId"]


# --- Refresh rotation + replay -------------------------------------------

async def test_refresh_rotates_and_replay_revokes_family(client):
    await register_user(client)
    original_refresh = client.cookies.get("refresh")
    csrf = client.cookies.get("csrf")
    assert original_refresh and csrf

    # First refresh: works, rotates.
    r1 = await client.post(
        "/api/auth/refresh",
        headers={"X-CSRF-Token": csrf},
    )
    assert r1.status_code == 200, r1.text
    new_refresh = client.cookies.get("refresh")
    new_csrf = client.cookies.get("csrf")
    assert new_refresh != original_refresh, "refresh cookie must rotate"

    # Replay the OLD refresh token → must fail and revoke the family.
    # Manually set the cookie to the original (httpx client has it rotated already).
    r2 = await client.post(
        "/api/auth/refresh",
        headers={"X-CSRF-Token": new_csrf, "Cookie": f"refresh={original_refresh}; csrf={new_csrf}"},
    )
    assert r2.status_code == 401
    assert r2.json()["detail"]["code"] == "REFRESH_REUSED"

    # Even the NEW refresh now shouldn't work — family revoked.
    r3 = await client.post(
        "/api/auth/refresh",
        headers={"X-CSRF-Token": new_csrf, "Cookie": f"refresh={new_refresh}; csrf={new_csrf}"},
    )
    assert r3.status_code == 401


async def test_refresh_without_csrf_is_rejected(client):
    await register_user(client)
    refresh_cookie = client.cookies.get("refresh")
    assert refresh_cookie
    # No X-CSRF-Token header.
    r = await client.post(
        "/api/auth/refresh",
        headers={"Cookie": f"refresh={refresh_cookie}"},
    )
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "CSRF_FAILED"


# --- Logout ---------------------------------------------------------------

async def test_logout_revokes_refresh(client):
    await register_user(client)
    refresh_cookie = client.cookies.get("refresh")
    csrf = client.cookies.get("csrf")

    r = await client.post("/api/auth/logout")
    assert r.status_code == 204

    # The logged-out refresh must no longer work.
    r2 = await client.post(
        "/api/auth/refresh",
        headers={"X-CSRF-Token": csrf, "Cookie": f"refresh={refresh_cookie}; csrf={csrf}"},
    )
    assert r2.status_code == 401


# --- OTP ------------------------------------------------------------------

async def test_otp_request_and_verify(client, monkeypatch):
    """Console SMS provider is the default under TESTING; we intercept the code
    generator so the test knows which 6-digit code to present."""
    fixed = "424242"
    monkeypatch.setattr("app.core.security.generate_otp_code", lambda: fixed)
    # The otp_service imports generate_otp_code from app.core.security;
    # patching the source module makes the binding in otp_service resolve to the stub.
    monkeypatch.setattr("app.services.otp_service.generate_otp_code", lambda: fixed)

    phone = "+15555550123"
    r1 = await client.post("/api/auth/phone/request-otp", json={"phone_number": phone})
    assert r1.status_code == 204, r1.text

    r2 = await client.post(
        "/api/auth/phone/verify-otp",
        json={"phone_number": phone, "code": fixed},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["accessToken"]
    assert r2.json()["user"]["phoneNumber"] == phone


async def test_otp_wrong_code_rejected(client, monkeypatch):
    monkeypatch.setattr("app.core.security.generate_otp_code", lambda: "111111")
    monkeypatch.setattr("app.services.otp_service.generate_otp_code", lambda: "111111")
    phone = "+15555550124"
    await client.post("/api/auth/phone/request-otp", json={"phone_number": phone})

    r = await client.post(
        "/api/auth/phone/verify-otp",
        json={"phone_number": phone, "code": "000000"},
    )
    assert r.status_code >= 400
    assert "error" in r.text.lower() or "otp" in r.text.lower() or "invalid" in r.text.lower()


# --- OAuth (mocked provider) ----------------------------------------------

async def test_oauth_google_callback_with_mocked_profile(client, monkeypatch):
    """We intercept GoogleProvider.exchange_code so the test doesn't need to
    hit real Google endpoints. A valid signed state token is still required."""
    from app.core import security
    from app.services import oauth_service

    state = security.encode_state_token({"prov": "google", "nonce": "xyz"})

    class FakeGoogle:
        name = "google"

        def __init__(self):
            pass

        def build_authorization_url(self, state: str) -> str:
            return "http://example.com/auth"

        async def exchange_code(self, code: str):
            return oauth_service.OAuthProfile(
                provider="google",
                provider_user_id="fake-google-sub-999",
                email=f"oauth-{secrets.token_hex(3)}@example.com",
                email_verified=True,
                display_name="OAuth User",
                raw={"sub": "fake-google-sub-999"},
            )

    monkeypatch.setattr(oauth_service, "GoogleProvider", FakeGoogle)

    r = await client.get(
        f"/api/auth/oauth/google/callback?code=fake-authorization-code&state={state}",
        follow_redirects=False,
    )
    # Callback issues a 302 redirect to the frontend with cookies set.
    assert r.status_code == 302, r.text
    assert "auth=success" in r.headers["location"]
    assert client.cookies.get("refresh")


async def test_oauth_callback_rejects_tampered_state(client):
    r = await client.get(
        "/api/auth/oauth/google/callback?code=fake&state=not-a-real-jwt",
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "OAUTH_BAD_STATE"


async def test_oauth_callback_error_param_redirects_to_frontend(client):
    """When the provider redirects back with ?error=access_denied (user
    cancelled), we redirect to the frontend with a readable reason instead of
    raising a 422 / 500."""
    r = await client.get(
        "/api/auth/oauth/google/callback?error=access_denied",
        follow_redirects=False,
    )
    assert r.status_code == 302
    loc = r.headers["location"]
    assert "auth=error" in loc
    assert "provider=google" in loc
    assert "reason=access_denied" in loc


async def test_oauth_callback_missing_code_redirects_to_frontend(client):
    """A callback hit without code/state/error (malformed provider response or
    a bot scan) shouldn't return a raw 422 — redirect with a generic reason."""
    r = await client.get(
        "/api/auth/oauth/google/callback",
        follow_redirects=False,
    )
    assert r.status_code == 302
    assert "auth=error" in r.headers["location"]
