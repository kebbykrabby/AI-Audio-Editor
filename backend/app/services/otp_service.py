from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import (
    generate_otp_code,
    otp_expiry,
    sha256_bytes,
)
from app.models.user import OtpCode
from app.services.auth_service import AuthError
from app.services.sms_service import get_sms_provider


async def _count_recent(
    db: AsyncSession,
    column,
    value: str,
    window: timedelta,
) -> int:
    since = datetime.utcnow() - window
    res = await db.execute(
        select(func.count())
        .select_from(OtpCode)
        .where(column == value, OtpCode.created_at >= since)
    )
    return int(res.scalar_one() or 0)


async def _check_rate_limits(db: AsyncSession, phone: str, ip: str | None) -> None:
    per_min = await _count_recent(db, OtpCode.phone_number, phone, timedelta(minutes=1))
    if per_min >= settings.OTP_RATE_PHONE_PER_MIN:
        raise AuthError("OTP_RATE_LIMITED", "Too many OTP requests for this phone number; try again shortly", 429)

    per_hour_phone = await _count_recent(db, OtpCode.phone_number, phone, timedelta(hours=1))
    if per_hour_phone >= settings.OTP_RATE_PHONE_PER_HOUR:
        raise AuthError("OTP_RATE_LIMITED", "Hourly OTP limit reached for this phone number", 429)

    if ip:
        per_hour_ip = await _count_recent(db, OtpCode.ip_address, ip, timedelta(hours=1))
        if per_hour_ip >= settings.OTP_RATE_IP_PER_HOUR:
            raise AuthError("OTP_RATE_LIMITED", "Hourly OTP limit reached from this address", 429)


async def request_otp(db: AsyncSession, phone_number: str, ip_address: str | None) -> None:
    await _check_rate_limits(db, phone_number, ip_address)
    code = generate_otp_code()
    db.add(OtpCode(
        phone_number=phone_number,
        code_hash=sha256_bytes(code),
        ip_address=ip_address,
        expires_at=otp_expiry(),
        attempts_remaining=settings.OTP_MAX_ATTEMPTS,
    ))
    await db.commit()

    provider = get_sms_provider()
    try:
        await provider.send_otp(phone_number, code)
    except Exception as e:
        raise AuthError("SMS_SEND_FAILED", f"Could not send verification code: {e}", 502)


async def verify_otp(
    db: AsyncSession,
    phone_number: str,
    code: str,
) -> None:
    res = await db.execute(
        select(OtpCode)
        .where(
            OtpCode.phone_number == phone_number,
            OtpCode.consumed_at.is_(None),
            OtpCode.expires_at >= datetime.utcnow(),
            OtpCode.attempts_remaining > 0,
        )
        .order_by(OtpCode.created_at.desc())
        .limit(1)
    )
    row = res.scalar_one_or_none()
    if row is None:
        raise AuthError("OTP_INVALID", "Invalid or expired verification code", 401)

    if row.code_hash != sha256_bytes(code):
        row.attempts_remaining -= 1
        await db.commit()
        raise AuthError("OTP_INVALID", "Invalid or expired verification code", 401)

    row.consumed_at = datetime.utcnow()
    await db.commit()
