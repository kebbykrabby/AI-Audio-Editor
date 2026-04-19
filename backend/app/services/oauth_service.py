import time
from pathlib import Path
from typing import Protocol
from urllib.parse import urlencode

import httpx
import jwt
from jwt import PyJWKClient

from app.config import settings
from app.services.auth_service import AuthError

GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISS = {"https://accounts.google.com", "accounts.google.com"}

APPLE_AUTH = "https://appleid.apple.com/auth/authorize"
APPLE_TOKEN = "https://appleid.apple.com/auth/token"
APPLE_JWKS = "https://appleid.apple.com/auth/keys"
APPLE_ISS = "https://appleid.apple.com"


class OAuthProfile(dict):
    """provider, provider_user_id, email, email_verified, display_name, raw"""


class OAuthProvider(Protocol):
    name: str

    def build_authorization_url(self, state: str) -> str: ...

    async def exchange_code(self, code: str) -> OAuthProfile: ...


def _ensure(cond: bool, code: str, msg: str, status: int = 400) -> None:
    if not cond:
        raise AuthError(code, msg, status)


class GoogleProvider:
    name = "google"

    def __init__(self) -> None:
        _ensure(
            bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET),
            "OAUTH_NOT_CONFIGURED",
            "Google OAuth is not configured",
            503,
        )
        self._jwks = PyJWKClient(GOOGLE_JWKS)

    def build_authorization_url(self, state: str) -> str:
        params = {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "redirect_uri": settings.GOOGLE_REDIRECT_URI,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "access_type": "online",
            "include_granted_scopes": "true",
            "prompt": "select_account",
        }
        return f"{GOOGLE_AUTH}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> OAuthProfile:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                GOOGLE_TOKEN,
                data={
                    "code": code,
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "redirect_uri": settings.GOOGLE_REDIRECT_URI,
                    "grant_type": "authorization_code",
                },
            )
        _ensure(resp.status_code < 400, "OAUTH_EXCHANGE_FAILED", "Google token exchange failed", 401)
        body = resp.json()
        id_token = body.get("id_token")
        _ensure(bool(id_token), "OAUTH_EXCHANGE_FAILED", "Google returned no id_token", 401)

        key = self._jwks.get_signing_key_from_jwt(id_token).key
        try:
            claims = jwt.decode(
                id_token,
                key,
                algorithms=["RS256"],
                audience=settings.GOOGLE_CLIENT_ID,
                options={"require": ["exp", "iat", "iss", "sub"]},
            )
        except jwt.InvalidTokenError as e:
            raise AuthError("OAUTH_INVALID_TOKEN", f"Invalid Google id_token: {e}", 401)

        _ensure(claims.get("iss") in GOOGLE_ISS, "OAUTH_INVALID_TOKEN", "Bad issuer", 401)

        return OAuthProfile(
            provider="google",
            provider_user_id=str(claims["sub"]),
            email=claims.get("email"),
            email_verified=bool(claims.get("email_verified")),
            display_name=claims.get("name"),
            raw=claims,
        )


class AppleProvider:
    name = "apple"

    def __init__(self) -> None:
        _ensure(
            bool(
                settings.APPLE_CLIENT_ID
                and settings.APPLE_TEAM_ID
                and settings.APPLE_KEY_ID
                and settings.APPLE_PRIVATE_KEY_PATH
            ),
            "OAUTH_NOT_CONFIGURED",
            "Apple OAuth is not configured",
            503,
        )
        self._jwks = PyJWKClient(APPLE_JWKS)

    def _client_secret(self) -> str:
        key_path = Path(settings.APPLE_PRIVATE_KEY_PATH)  # type: ignore[arg-type]
        _ensure(key_path.exists(), "OAUTH_NOT_CONFIGURED", "Apple private key file missing", 503)
        private_key = key_path.read_text()
        now = int(time.time())
        payload = {
            "iss": settings.APPLE_TEAM_ID,
            "iat": now,
            "exp": now + 300,
            "aud": APPLE_ISS,
            "sub": settings.APPLE_CLIENT_ID,
        }
        headers = {"kid": settings.APPLE_KEY_ID, "alg": "ES256"}
        return jwt.encode(payload, private_key, algorithm="ES256", headers=headers)

    def build_authorization_url(self, state: str) -> str:
        params = {
            "client_id": settings.APPLE_CLIENT_ID,
            "redirect_uri": settings.APPLE_REDIRECT_URI,
            "response_type": "code",
            "scope": "name email",
            "response_mode": "form_post",
            "state": state,
        }
        return f"{APPLE_AUTH}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> OAuthProfile:
        client_secret = self._client_secret()
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                APPLE_TOKEN,
                data={
                    "code": code,
                    "client_id": settings.APPLE_CLIENT_ID,
                    "client_secret": client_secret,
                    "redirect_uri": settings.APPLE_REDIRECT_URI,
                    "grant_type": "authorization_code",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        _ensure(resp.status_code < 400, "OAUTH_EXCHANGE_FAILED", "Apple token exchange failed", 401)
        body = resp.json()
        id_token = body.get("id_token")
        _ensure(bool(id_token), "OAUTH_EXCHANGE_FAILED", "Apple returned no id_token", 401)

        key = self._jwks.get_signing_key_from_jwt(id_token).key
        try:
            claims = jwt.decode(
                id_token,
                key,
                algorithms=["ES256"],
                audience=settings.APPLE_CLIENT_ID,
                options={"require": ["exp", "iat", "iss", "sub"]},
            )
        except jwt.InvalidTokenError as e:
            raise AuthError("OAUTH_INVALID_TOKEN", f"Invalid Apple id_token: {e}", 401)

        _ensure(claims.get("iss") == APPLE_ISS, "OAUTH_INVALID_TOKEN", "Bad issuer", 401)

        return OAuthProfile(
            provider="apple",
            provider_user_id=str(claims["sub"]),
            email=claims.get("email"),
            email_verified=bool(claims.get("email_verified") in (True, "true")),
            display_name=None,
            raw=claims,
        )


def get_provider(name: str) -> OAuthProvider:
    if name == "google":
        return GoogleProvider()
    if name == "apple":
        return AppleProvider()
    raise AuthError("OAUTH_UNKNOWN_PROVIDER", f"Unknown OAuth provider: {name}", 400)
