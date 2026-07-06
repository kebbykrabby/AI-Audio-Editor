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
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Per-user overrides for the curse-word censorship feature. Shape:
    #   {"added": ["word1", ...], "removed": ["builtin_word1", ...]}
    # Effective list = (BUILT_IN - removed) ∪ added. See `censorship_service`.
    # Default-empty so existing users transparently inherit the built-in list.
    censorship_words: Mapped[dict] = mapped_column(JSON_COL, nullable=False, default=dict)
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


class EmailVerificationCode(Base):
    """One-time code used to verify a user's email before their first export.

    Codes are 6 digits; the DB row stores only a SHA-256 hash so a leaked backup
    can't be replayed. `attempts_remaining` guards against online guessing.
    """
    __tablename__ = "email_verification_codes"
    __table_args__ = (
        Index("ix_email_verify_user_created", "user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        UUID_COL, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    code_hash: Mapped[bytes] = mapped_column(LargeBinary(32))
    expires_at: Mapped[datetime] = mapped_column()
    attempts_remaining: Mapped[int] = mapped_column(SmallInteger, default=5)
    consumed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

