import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import UUID_COL, Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Analysis(Base):
    __tablename__ = "analyses"
    __table_args__ = (
        UniqueConstraint("asset_id", "kind", "model_version", name="uq_analyses_kind"),
        Index("ix_analyses_user_created", "user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        UUID_COL, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    asset_id: Mapped[str] = mapped_column(
        UUID_COL, ForeignKey("assets.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(40))
    model_version: Mapped[str] = mapped_column(String(80))
    storage_key: Mapped[str] = mapped_column(String(500))
    language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Numeric(10, 6), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
