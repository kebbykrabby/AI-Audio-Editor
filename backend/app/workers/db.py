from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings


def _to_sync_url(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    if url.startswith("sqlite+aiosqlite://"):
        # Tests use aiosqlite for the API; workers need the sync pysqlite driver
        # pointing at the same file.
        return url.replace("sqlite+aiosqlite://", "sqlite://", 1)
    return url


sync_engine = create_engine(
    _to_sync_url(settings.DATABASE_URL),
    pool_pre_ping=True,
    future=True,
)

SyncSession = sessionmaker(sync_engine, class_=Session, expire_on_commit=False)
