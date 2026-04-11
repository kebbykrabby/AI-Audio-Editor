from datetime import datetime

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    type: Mapped[str] = mapped_column(String(20))  # "original" | "derived"
    status: Mapped[str] = mapped_column(String(20), default="processing")
    parent_asset_id: Mapped[str | None] = mapped_column(
        String(80), ForeignKey("assets.id"), nullable=True, index=True
    )
    filename: Mapped[str] = mapped_column(String(255), default="")
    duration_sec: Mapped[float | None] = mapped_column(nullable=True)
    sample_rate: Mapped[int | None] = mapped_column(nullable=True)
    channels: Mapped[int | None] = mapped_column(nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, onupdate=datetime.utcnow
    )
