import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Numeric, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import JSON_COL, UUID_COL, Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Operation(Base):
    __tablename__ = "operations"
    __table_args__ = (
        Index("ix_operations_status_queued_at", "status", "queued_at"),
        Index("ix_operations_user_created", "user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        UUID_COL, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(String(40))
    input_asset_id: Mapped[str] = mapped_column(
        UUID_COL, ForeignKey("assets.id"), index=True
    )
    output_asset_id: Mapped[str | None] = mapped_column(
        UUID_COL, ForeignKey("assets.id"), nullable=True, index=True
    )
    secondary_output_asset_id: Mapped[str | None] = mapped_column(
        UUID_COL, ForeignKey("assets.id"), nullable=True
    )
    parameters: Mapped[dict] = mapped_column(JSON_COL, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON_COL, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Numeric(10, 6), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    warning: Mapped[str | None] = mapped_column(Text, nullable=True)
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
