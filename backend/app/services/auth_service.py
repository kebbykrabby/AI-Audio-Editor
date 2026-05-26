from datetime import datetime
from typing import NamedTuple

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import (
    encode_access_token,
    generate_csrf_token,
    generate_opaque_token,
    hash_password,
    refresh_token_expiry,
    sha256_bytes,
    verify_password,
)
from app.models.user import Identity, RefreshToken, User


class AuthError(Exception):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


class IssuedTokens(NamedTuple):
    access_token: str
    access_ttl_sec: int
    refresh_token_plain: str
    csrf_token: str
    refresh_row: RefreshToken


def _normalize_email(email: str) -> str:
    return email.strip().lower()


async def _find_user_by_email(db: AsyncSession, email: str) -> User | None:
    res = await db.execute(select(User).where(User.email == email))
    return res.scalar_one_or_none()


async def _find_user_by_phone(db: AsyncSession, phone: str) -> User | None:
    res = await db.execute(select(User).where(User.phone_number == phone))
    return res.scalar_one_or_none()


async def issue_tokens(
    db: AsyncSession,
    user: User,
    user_agent: str | None,
    ip_address: str | None,
    parent_id: str | None = None,
) -> IssuedTokens:
    access = encode_access_token(user.id)
    opaque = generate_opaque_token()
    row = RefreshToken(
        user_id=user.id,
        token_hash=sha256_bytes(opaque),
        parent_id=parent_id,
        user_agent=(user_agent or "")[:500] or None,
        ip_address=(ip_address or "")[:64] or None,
        expires_at=refresh_token_expiry(),
    )
    db.add(row)
    await db.flush()
    csrf = generate_csrf_token()
    return IssuedTokens(
        access_token=access,
        access_ttl_sec=settings.JWT_ACCESS_TTL_MIN * 60,
        refresh_token_plain=opaque,
        csrf_token=csrf,
        refresh_row=row,
    )


async def register_with_email(
    db: AsyncSession,
    email: str,
    password: str,
    display_name: str | None,
    user_agent: str | None,
    ip_address: str | None,
) -> tuple[User, IssuedTokens]:
    email_n = _normalize_email(email)
    if await _find_user_by_email(db, email_n) is not None:
        raise AuthError("EMAIL_TAKEN", "An account with this email already exists", 409)

    user = User(
        email=email_n,
        password_hash=hash_password(password),
        display_name=display_name,
    )
    db.add(user)
    await db.flush()

    db.add(Identity(
        user_id=user.id,
        provider="email",
        provider_user_id=email_n,
        email_from_provider=email_n,
    ))

    tokens = await issue_tokens(db, user, user_agent, ip_address)
    await db.commit()
    return user, tokens


async def login_with_email(
    db: AsyncSession,
    email: str,
    password: str,
    user_agent: str | None,
    ip_address: str | None,
) -> tuple[User, IssuedTokens]:
    email_n = _normalize_email(email)
    user = await _find_user_by_email(db, email_n)
    if user is None or user.password_hash is None or user.deleted_at is not None:
        raise AuthError("INVALID_CREDENTIALS", "Invalid email or password", 401)
    if not verify_password(password, user.password_hash):
        raise AuthError("INVALID_CREDENTIALS", "Invalid email or password", 401)

    tokens = await issue_tokens(db, user, user_agent, ip_address)
    await db.commit()
    return user, tokens


async def _load_refresh_by_plain(db: AsyncSession, plain: str) -> RefreshToken | None:
    res = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == sha256_bytes(plain))
    )
    return res.scalar_one_or_none()


async def _revoke_family(db: AsyncSession, user_id: str) -> None:
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.utcnow())
    )


async def refresh(
    db: AsyncSession,
    refresh_token_plain: str,
    user_agent: str | None,
    ip_address: str | None,
) -> tuple[User, IssuedTokens]:
    row = await _load_refresh_by_plain(db, refresh_token_plain)
    if row is None:
        raise AuthError("INVALID_REFRESH", "Invalid refresh token", 401)
    if row.expires_at < datetime.utcnow():
        raise AuthError("REFRESH_EXPIRED", "Refresh token expired", 401)
    if row.revoked_at is not None:
        # Replay of a revoked token — mass-revoke the whole family.
        await _revoke_family(db, row.user_id)
        await db.commit()
        raise AuthError("REFRESH_REUSED", "Refresh token reuse detected", 401)

    user = await db.get(User, row.user_id)
    if user is None or user.deleted_at is not None:
        raise AuthError("INVALID_REFRESH", "Invalid refresh token", 401)

    # Rotate: revoke current and issue new linked to parent.
    row.revoked_at = datetime.utcnow()
    tokens = await issue_tokens(db, user, user_agent, ip_address, parent_id=row.id)
    await db.commit()
    return user, tokens


async def logout(db: AsyncSession, refresh_token_plain: str | None) -> None:
    if not refresh_token_plain:
        return
    row = await _load_refresh_by_plain(db, refresh_token_plain)
    if row is not None and row.revoked_at is None:
        row.revoked_at = datetime.utcnow()
        await db.commit()


async def link_or_create_for_oauth(
    db: AsyncSession,
    provider: str,
    provider_user_id: str,
    email: str | None,
    email_verified: bool,
    display_name: str | None,
    raw_profile: dict,
    user_agent: str | None,
    ip_address: str | None,
) -> tuple[User, IssuedTokens]:
    # Look up by existing identity first.
    res = await db.execute(
        select(Identity).where(
            Identity.provider == provider,
            Identity.provider_user_id == provider_user_id,
        )
    )
    identity = res.scalar_one_or_none()
    if identity is not None:
        user = await db.get(User, identity.user_id)
        if user is None or user.deleted_at is not None:
            raise AuthError("ACCOUNT_DISABLED", "Account is disabled", 401)
        identity.last_used_at = datetime.utcnow()
        identity.raw_profile = raw_profile
    else:
        user = None
        if email and email_verified:
            user = await _find_user_by_email(db, _normalize_email(email))

        if user is None:
            user = User(
                email=_normalize_email(email) if email else None,
                email_verified_at=datetime.utcnow() if email_verified else None,
                display_name=display_name,
            )
            db.add(user)
            await db.flush()

        db.add(Identity(
            user_id=user.id,
            provider=provider,
            provider_user_id=provider_user_id,
            email_from_provider=email,
            raw_profile=raw_profile,
        ))

    tokens = await issue_tokens(db, user, user_agent, ip_address)
    await db.commit()
    return user, tokens


async def link_or_create_for_phone(
    db: AsyncSession,
    phone_number: str,
    user_agent: str | None,
    ip_address: str | None,
) -> tuple[User, IssuedTokens]:
    user = await _find_user_by_phone(db, phone_number)
    if user is None:
        user = User(
            phone_number=phone_number,
            phone_verified_at=datetime.utcnow(),
        )
        db.add(user)
        await db.flush()
        db.add(Identity(
            user_id=user.id,
            provider="phone",
            provider_user_id=phone_number,
        ))
    elif user.phone_verified_at is None:
        user.phone_verified_at = datetime.utcnow()

    tokens = await issue_tokens(db, user, user_agent, ip_address)
    await db.commit()
    return user, tokens
