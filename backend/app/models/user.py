import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, LargeBinary, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import JSON_COL, UUID_COL, Base


def _uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    email: Mapped[str | None] = mapped_column(String(320), unique=True, nullable=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(nullable=True)
    phone_number: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True)
    phone_verified_at: Mapped[datetime | None] = mapped_column(nullable=True)
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, onupdate=datetime.utcnow
    )
    deleted_at: Mapped[datetime | None] = mapped_column(nullable=True)


class Identity(Base):
    __tablename__ = "identities"
    __table_args__ = (
        Index(
            "ix_identities_provider_provider_user_id",
            "provider",
            "provider_user_id",
            unique=True,
        ),
    )

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        UUID_COL, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(20))
    provider_user_id: Mapped[str] = mapped_column(String(320))
    email_from_provider: Mapped[str | None] = mapped_column(String(320), nullable=True)
    raw_profile: Mapped[dict | None] = mapped_column(JSON_COL, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    last_used_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, onupdate=datetime.utcnow
    )


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = (
        Index("ix_refresh_tokens_user_expires", "user_id", "expires_at"),
    )

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        UUID_COL, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), unique=True)
    parent_id: Mapped[str | None] = mapped_column(
        UUID_COL, ForeignKey("refresh_tokens.id"), nullable=True
    )
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[datetime] = mapped_column()
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)


class OtpCode(Base):
    __tablename__ = "otp_codes"
    __table_args__ = (
        Index("ix_otp_phone_created", "phone_number", "created_at"),
        Index("ix_otp_ip_created", "ip_address", "created_at"),
    )

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    phone_number: Mapped[str] = mapped_column(String(32))
    code_hash: Mapped[bytes] = mapped_column(LargeBinary(32))
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[datetime] = mapped_column()
    attempts_remaining: Mapped[int] = mapped_column(SmallInteger, default=5)
    consumed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
