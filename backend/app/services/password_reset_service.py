"""Password reset — request + verify + apply.

Flow:
1. `request_code(db, email)` — anon caller supplies an email. If we recognize it,
   we generate a 6-digit code, store its SHA-256 with a 15-min expiry, and send
   it via `email_service`. If the email is unknown we return 204 anyway
   (prevents user enumeration).
2. `reset_password(db, email, code, new_password)` — verify the code, replace
   the user's password_hash, and revoke every outstanding refresh token so any
   attacker who had the old password gets logged out too.

Rate-limited per user (1/min, 5/hour) using `password_reset_codes.created_at`,
mirroring the email-verification service. Old unconsumed codes for the same
user are invalidated when a new one is requested.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import (
    generate_otp_code,
    hash_password,
    password_reset_expiry,
    sha256_bytes,
)
from app.models.user import PasswordResetCode, RefreshToken, User
from app.services.auth_service import AuthError
from app.services.email_service import send_password_reset_email


def _normalize_email(email: str) -> str:
    return email.strip().lower()


async def _find_user_by_email(db: AsyncSession, email: str) -> User | None:
    res = await db.execute(select(User).where(User.email == _normalize_email(email)))
    return res.scalar_one_or_none()


async def _count_recent_codes(
    db: AsyncSession, user_id: str, window: timedelta
) -> int:
    since = datetime.utcnow() - window
    res = await db.execute(
        select(func.count())
        .select_from(PasswordResetCode)
        .where(
            PasswordResetCode.user_id == user_id,
            PasswordResetCode.created_at >= since,
        )
    )
    return int(res.scalar_one() or 0)


async def _invalidate_outstanding(db: AsyncSession, user_id: str) -> None:
    await db.execute(
        update(PasswordResetCode)
        .where(
            PasswordResetCode.user_id == user_id,
            PasswordResetCode.consumed_at.is_(None),
        )
        .values(consumed_at=datetime.utcnow())
    )


async def request_code(db: AsyncSession, email: str) -> None:
    """Silently succeed even if the email isn't registered (anti-enumeration).

    When the email IS registered and the user has a password (i.e. not
    OAuth-only), we generate + send a code. If they're OAuth-only, we still
    silently succeed rather than telling the caller "this is a Google account
    — sign in with Google" — that would be an enumeration signal too.
    """
    user = await _find_user_by_email(db, email)
    if user is None or user.deleted_at is not None or user.password_hash is None:
        return

    per_min = await _count_recent_codes(db, user.id, timedelta(minutes=1))
    if per_min >= settings.PASSWORD_RESET_RATE_PER_MIN:
        # Rate-limit silently too — an attacker who can trigger 429s learns
        # nothing they didn't already know (they saw at least one 204).
        return
    per_hour = await _count_recent_codes(db, user.id, timedelta(hours=1))
    if per_hour >= settings.PASSWORD_RESET_RATE_PER_HOUR:
        return

    await _invalidate_outstanding(db, user.id)

    code = generate_otp_code()
    row = PasswordResetCode(
        user_id=user.id,
        code_hash=sha256_bytes(code),
        expires_at=password_reset_expiry(),
        attempts_remaining=settings.PASSWORD_RESET_MAX_ATTEMPTS,
    )
    db.add(row)
    await db.commit()

    await send_password_reset_email(user.email, code)


async def reset_password(
    db: AsyncSession, email: str, code: str, new_password: str
) -> None:
    """Consume the code and set a new password_hash.

    On success, revokes ALL of this user's refresh tokens so any session an
    attacker might have opened with the old password is invalidated.

    Errors surface as AuthError:
      - CODE_EXPIRED_OR_MISSING  — no live code for this email
      - CODE_INVALID             — wrong code, attempts remain
      - CODE_EXHAUSTED           — no attempts left; must request a new code
      - INVALID_CREDENTIALS      — email unknown (kept generic to avoid enum)
    """
    if len(new_password) < 8 or len(new_password) > 256:
        raise AuthError(
            "INVALID_PARAMETERS",
            "Password must be 8 to 256 characters",
            status=400,
        )

    user = await _find_user_by_email(db, email)
    if user is None or user.deleted_at is not None or user.password_hash is None:
        # Same code as login for parity — attacker can't tell if the email is
        # registered vs the code is wrong.
        raise AuthError(
            "CODE_EXPIRED_OR_MISSING",
            "This code has expired or is not valid",
            status=400,
        )

    now = datetime.utcnow()
    res = await db.execute(
        select(PasswordResetCode)
        .where(
            PasswordResetCode.user_id == user.id,
            PasswordResetCode.consumed_at.is_(None),
            PasswordResetCode.expires_at > now,
        )
        .order_by(PasswordResetCode.created_at.desc())
        .limit(1)
    )
    row = res.scalar_one_or_none()
    if row is None:
        raise AuthError(
            "CODE_EXPIRED_OR_MISSING",
            "This code has expired — request a new one",
            status=400,
        )

    if row.code_hash != sha256_bytes(code.strip()):
        row.attempts_remaining -= 1
        if row.attempts_remaining <= 0:
            row.consumed_at = now
            await db.commit()
            raise AuthError(
                "CODE_EXHAUSTED",
                "Too many wrong attempts — request a new code",
                status=400,
            )
        await db.commit()
        raise AuthError(
            "CODE_INVALID",
            f"Wrong code — {row.attempts_remaining} attempt(s) left",
            status=400,
        )

    row.consumed_at = now
    user.password_hash = hash_password(new_password)

    # Revoke every outstanding refresh token for this user — any attacker who
    # had the old password loses their session too.
    await db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.user_id == user.id,
            RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    await db.commit()
