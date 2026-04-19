import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import UUID_COL, Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Export(Base):
    __tablename__ = "exports"
    __table_args__ = (
        Index("ix_exports_user_created", "user_id", "created_at"),
        Index("ix_exports_status_queued_at", "status", "queued_at"),
    )

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        UUID_COL, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    source_asset_id: Mapped[str] = mapped_column(
        UUID_COL, ForeignKey("assets.id"), index=True
    )
    format: Mapped[str] = mapped_column(String(10))  # "wav" | "mp3"
    sample_rate: Mapped[int | None] = mapped_column(nullable=True)
    bitrate_kbps: Mapped[int | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    storage_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt_count: Mapped[int] = mapped_column(SmallInteger, default=0)
    worker_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    queued_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, onupdate=datetime.utcnow
    )
