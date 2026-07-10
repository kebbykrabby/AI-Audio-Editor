import uuid
from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, Index, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import UUID_COL, Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Asset(Base):
    __tablename__ = "assets"
    __table_args__ = (
        Index("ix_assets_user_created", "user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        UUID_COL, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(String(20))  # "original" | "derived"
    status: Mapped[str] = mapped_column(String(20), default="processing")
    parent_asset_id: Mapped[str | None] = mapped_column(
        UUID_COL, ForeignKey("assets.id"), nullable=True, index=True
    )
    storage_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    waveform_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    filename: Mapped[str] = mapped_column(String(255), default="")
    mime_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    duration_sec: Mapped[float | None] = mapped_column(nullable=True)
    sample_rate: Mapped[int | None] = mapped_column(nullable=True)
    channels: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, onupdate=datetime.utcnow
    )
    # Soft-delete: filled when the user deletes a project from the Dashboard.
    # `get_asset_for_user` intentionally does NOT filter on this so an in-progress
    # editor session continues to work; list-assets and dashboard queries do.
    deleted_at: Mapped[datetime | None] = mapped_column(nullable=True)
