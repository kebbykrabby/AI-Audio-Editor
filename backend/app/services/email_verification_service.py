"""Email verification: request a 6-digit code + verify it.

Gate: `require_email_verified(user)` — call this at any point where we want to
force a verified email (the export API is the only caller today).

Flow:
1. `request_code(db, user)` — generates a fresh 6-digit code, stores a SHA-256
   of it with a 15-min expiry, and sends it via `email_service`. Rate-limited
   per user (1/min, 5/hour) via `email_verification_codes.created_at`.
2. `verify_code(db, user, code)` — looks up the latest unconsumed unexpired
   row for the user, compares the hash, and sets `user.email_verified_at`.
   Decrements `attempts_remaining` on mismatch. When it hits zero, the row is
   marked consumed and the user must request a new one.

Design notes:
- The code hash is stored, not the code itself. A leaked DB backup can't be
  replayed against production.
- Codes are one-off: on successful verification we mark the row consumed AND
  set the user's `email_verified_at`, so the same code can't be reused.
- Old unconsumed codes for the same user are invalidated when a new one is
  requested — otherwise a user could accumulate valid codes.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import (
    email_verify_expiry,
    generate_otp_code,
    sha256_bytes,
)
from app.models.user import EmailVerificationCode, User
from app.services.auth_service import AuthError
from app.services.email_service import send_verification_email


class EmailVerificationRequired(AuthError):
    """Raised by `require_email_verified` when the caller's email is unverified.

    Wrapped by API layer into HTTP 403 with code EMAIL_VERIFICATION_REQUIRED so
    the frontend can pop the verification modal instead of showing a generic
    error.
    """

    def __init__(self) -> None:
        super().__init__(
            "EMAIL_VERIFICATION_REQUIRED",
            "Please verify your email to continue",
            status=403,
        )


def require_email_verified(user: User) -> None:
    """Raise EmailVerificationRequired if user's email isn't verified.

    Users created via OAuth with a provider-verified email will have
    `email_verified_at` set at link time — those pass through. Password-signup
    users won't until they complete the flow.
    """
    if user.email is None or user.email_verified_at is None:
        raise EmailVerificationRequired()


async def _count_recent_codes(
    db: AsyncSession, user_id: str, window: timedelta
) -> int:
    since = datetime.utcnow() - window
    res = await db.execute(
        select(func.count())
        .select_from(EmailVerificationCode)
        .where(
            EmailVerificationCode.user_id == user_id,
            EmailVerificationCode.created_at >= since,
        )
    )
    return int(res.scalar_one() or 0)


async def _invalidate_outstanding(db: AsyncSession, user_id: str) -> None:
    """Consume any unconsumed unexpired codes for this user.

    Called right before we issue a new one so the user can't accumulate valid
    codes (or a stolen prior code stays live).
    """
    await db.execute(
        update(EmailVerificationCode)
        .where(
            EmailVerificationCode.user_id == user_id,
            EmailVerificationCode.consumed_at.is_(None),
        )
        .values(consumed_at=datetime.utcnow())
    )


async def request_code(db: AsyncSession, user: User) -> None:
    """Generate + email a fresh 6-digit code. Rate-limited per user.

    No return: the code itself is only ever in the email + the DB hash.
    """
    if user.email is None:
        raise AuthError(
            "NO_EMAIL_ON_ACCOUNT",
            "This account has no email address to verify",
            status=400,
        )
    if user.email_verified_at is not None:
        raise AuthError(
            "EMAIL_ALREADY_VERIFIED",
            "This email is already verified",
            status=409,
        )

    per_min = await _count_recent_codes(db, user.id, timedelta(minutes=1))
    if per_min >= settings.EMAIL_VERIFY_RATE_PER_MIN:
        raise AuthError(
            "EMAIL_VERIFY_RATE_LIMITED",
            "Please wait a moment before requesting another code",
            status=429,
        )
    per_hour = await _count_recent_codes(db, user.id, timedelta(hours=1))
    if per_hour >= settings.EMAIL_VERIFY_RATE_PER_HOUR:
        raise AuthError(
            "EMAIL_VERIFY_RATE_LIMITED",
            "Too many code requests; please try again in an hour",
            status=429,
        )

    await _invalidate_outstanding(db, user.id)

    code = generate_otp_code()
    row = EmailVerificationCode(
        user_id=user.id,
        code_hash=sha256_bytes(code),
        expires_at=email_verify_expiry(),
        attempts_remaining=settings.EMAIL_VERIFY_MAX_ATTEMPTS,
    )
    db.add(row)
    await db.commit()

    # Send AFTER commit so a mid-send failure doesn't leave a stored code that
    # was never delivered. The tradeoff: if the email fails, the DB has an
    # unused code — but the user can just request again and the older one gets
    # invalidated.
    await send_verification_email(user.email, code)


async def verify_code(db: AsyncSession, user: User, code: str) -> None:
    """Consume the latest live code for `user` and mark email verified.

    Errors surface as AuthError with codes the frontend can map to messages:
      - CODE_EXPIRED_OR_MISSING
      - CODE_INVALID (attempts remain)
      - CODE_EXHAUSTED (last attempt burned)
    """
    if user.email is None:
        raise AuthError("NO_EMAIL_ON_ACCOUNT", "No email to verify", status=400)
    if user.email_verified_at is not None:
        # idempotent — treat re-verify as a no-op success
        return

    now = datetime.utcnow()
    res = await db.execute(
        select(EmailVerificationCode)
        .where(
            EmailVerificationCode.user_id == user.id,
            EmailVerificationCode.consumed_at.is_(None),
            EmailVerificationCode.expires_at > now,
        )
        .order_by(EmailVerificationCode.created_at.desc())
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
    user.email_verified_at = now
    await db.commit()
