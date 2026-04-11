from datetime import datetime

from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Operation(Base):
    __tablename__ = "operations"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    type: Mapped[str] = mapped_column(String(30))
    input_asset_id: Mapped[str] = mapped_column(
        String(80), ForeignKey("assets.id"), index=True
    )
    output_asset_id: Mapped[str | None] = mapped_column(
        String(80), ForeignKey("assets.id"), nullable=True, index=True
    )
    parameters: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="completed")
    warning: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
