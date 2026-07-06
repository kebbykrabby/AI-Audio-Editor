import secrets
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.deps import get_current_user
from app.core.security import decode_state_token, encode_state_token
from app.database import get_db
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    OAuthStartResponse,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.services import auth_service, oauth_service
from app.services.auth_service import AuthError

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()[:64]
    return request.client.host if request.client else None


def _user_agent(request: Request) -> str | None:
    return (request.headers.get("user-agent") or "")[:500] or None


def _user_to_response(user: User) -> UserResponse:
    return UserResponse(
        userId=user.id,
        email=user.email,
        displayName=user.display_name,
        emailVerified=user.email_verified_at is not None,
    )


def _set_auth_cookies(response: Response, refresh_plain: str, csrf: str) -> None:
    response.set_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        value=refresh_plain,
        max_age=settings.REFRESH_TTL_DAYS * 24 * 3600,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        path="/api/auth",
        domain=settings.COOKIE_DOMAIN,
    )
    response.set_cookie(
        key=settings.CSRF_COOKIE_NAME,
        value=csrf,
        max_age=settings.REFRESH_TTL_DAYS * 24 * 3600,
        httponly=False,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        path="/",
        domain=settings.COOKIE_DOMAIN,
    )


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(settings.REFRESH_COOKIE_NAME, path="/api/auth", domain=settings.COOKIE_DOMAIN)
    response.delete_cookie(settings.CSRF_COOKIE_NAME, path="/", domain=settings.COOKIE_DOMAIN)


def _auth_error_http(e: AuthError) -> HTTPException:
    return HTTPException(status_code=e.status, detail={"code": e.code, "message": e.message})


def _check_csrf(request: Request) -> None:
    header_val = request.headers.get(settings.CSRF_HEADER_NAME)
    cookie_val = request.cookies.get(settings.CSRF_COOKIE_NAME)
    if not header_val or not cookie_val or not secrets.compare_digest(header_val, cookie_val):
        raise HTTPException(status_code=403, detail={"code": "CSRF_FAILED", "message": "Missing or invalid CSRF token"})


def _token_response(user: User, access: str, ttl_sec: int) -> TokenResponse:
    return TokenResponse(
        accessToken=access,
        expiresIn=ttl_sec,
        user=_user_to_response(user),
    )


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(
    body: RegisterRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)
):
    try:
        user, tokens = await auth_service.register_with_email(
            db,
            body.email,
            body.password,
            body.display_name,
            _user_agent(request),
            _client_ip(request),
        )
    except AuthError as e:
        raise _auth_error_http(e)
    _set_auth_cookies(response, tokens.refresh_token_plain, tokens.csrf_token)
    return _token_response(user, tokens.access_token, tokens.access_ttl_sec)


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)
):
    try:
        user, tokens = await auth_service.login_with_email(
            db,
            body.email,
            body.password,
            _user_agent(request),
            _client_ip(request),
        )
    except AuthError as e:
        raise _auth_error_http(e)
    _set_auth_cookies(response, tokens.refresh_token_plain, tokens.csrf_token)
    return _token_response(user, tokens.access_token, tokens.access_ttl_sec)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    _check_csrf(request)
    refresh_cookie = request.cookies.get(settings.REFRESH_COOKIE_NAME)
    if not refresh_cookie:
        raise HTTPException(status_code=401, detail={"code": "INVALID_REFRESH", "message": "No refresh token"})
    try:
        user, tokens = await auth_service.refresh(
            db, refresh_cookie, _user_agent(request), _client_ip(request)
        )
    except AuthError as e:
        if e.code == "REFRESH_REUSED":
            _clear_auth_cookies(response)
        raise _auth_error_http(e)
    _set_auth_cookies(response, tokens.refresh_token_plain, tokens.csrf_token)
    return _token_response(user, tokens.access_token, tokens.access_ttl_sec)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    refresh_cookie = request.cookies.get(settings.REFRESH_COOKIE_NAME)
    await auth_service.logout(db, refresh_cookie)
    _clear_auth_cookies(response)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserResponse)
async def me(user: User = Depends(get_current_user)):
    return _user_to_response(user)


# ----- OAuth (Google & Apple) -----

@router.get("/oauth/{provider}/start", response_model=OAuthStartResponse)
async def oauth_start(provider: str):
    try:
        prov = oauth_service.get_provider(provider)
    except AuthError as e:
        raise _auth_error_http(e)
    state = encode_state_token({"prov": provider, "nonce": secrets.token_urlsafe(16)})
    return OAuthStartResponse(redirectUrl=prov.build_authorization_url(state))


async def _oauth_complete(
    provider: str,
    code: str,
    state: str,
    request: Request,
    db: AsyncSession,
) -> RedirectResponse:
    try:
        claims = decode_state_token(state)
    except Exception:
        raise HTTPException(status_code=400, detail={"code": "OAUTH_BAD_STATE", "message": "Invalid OAuth state"})
    if claims.get("prov") != provider:
        raise HTTPException(status_code=400, detail={"code": "OAUTH_BAD_STATE", "message": "Provider mismatch in state"})

    try:
        prov = oauth_service.get_provider(provider)
        profile = await prov.exchange_code(code)
        user, tokens = await auth_service.link_or_create_for_oauth(
            db,
            provider=profile["provider"],
            provider_user_id=profile["provider_user_id"],
            email=profile.get("email"),
            email_verified=bool(profile.get("email_verified")),
            display_name=profile.get("display_name"),
            raw_profile=profile.get("raw") or {},
            user_agent=_user_agent(request),
            ip_address=_client_ip(request),
        )
    except AuthError as e:
        raise _auth_error_http(e)

    redirect_qs = urlencode({"auth": "success"})
    redirect = RedirectResponse(url=f"{settings.FRONTEND_BASE_URL}/?{redirect_qs}", status_code=302)
    _set_auth_cookies(redirect, tokens.refresh_token_plain, tokens.csrf_token)
    return redirect


def _oauth_error_redirect(provider: str, reason: str) -> RedirectResponse:
    """Redirect the browser back to the frontend with a readable error reason.

    Used when the provider cancels/declines (Google: ?error=access_denied, etc.)
    so the user sees a clean message instead of a 422 / white screen.
    """
    qs = urlencode({"auth": "error", "provider": provider, "reason": reason[:200]})
    return RedirectResponse(url=f"{settings.FRONTEND_BASE_URL}/?{qs}", status_code=302)


@router.get("/oauth/google/callback")
async def oauth_google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    if error:
        return _oauth_error_redirect("google", error)
    if not code or not state:
        return _oauth_error_redirect("google", "missing_code_or_state")
    return await _oauth_complete("google", code, state, request, db)


@router.post("/oauth/apple/callback")
async def oauth_apple_callback(
    request: Request,
    db: AsyncSession = Depends(get_db),
    code: str | None = Form(None),
    state: str | None = Form(None),
    error: str | None = Form(None),
):
    # Apple uses form_post; see AppleProvider.build_authorization_url.
    if error:
        return _oauth_error_redirect("apple", error)
    if not code or not state:
        return _oauth_error_redirect("apple", "missing_code_or_state")
    return await _oauth_complete("apple", code, state, request, db)
