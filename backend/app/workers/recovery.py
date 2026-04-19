import logging
import os
import socket
from datetime import datetime, timedelta

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.config import settings
from app.models.export import Export
from app.models.operation import Operation

logger = logging.getLogger(__name__)


def worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def recover_orphaned_for_this_worker(db: Session) -> int:
    wid = worker_id()
    total = 0
    now = datetime.utcnow()
    for Model in (Operation, Export):
        result = db.execute(
            update(Model)
            .where(Model.worker_id == wid, Model.status == "running")
            .values(
                status="failed",
                error_code="SERVER_RESTART",
                error_message="Operation interrupted by worker restart",
                completed_at=now,
            )
        )
        total += result.rowcount or 0
    db.commit()
    if total:
        logger.info("Worker recovery: marked %d orphaned job(s) as failed (worker_id=%s)", total, wid)
    return total


async def recover_stale_running(db: AsyncSession) -> int:
    cutoff = datetime.utcnow() - timedelta(minutes=settings.WORKER_STALE_RUNNING_MIN)
    now = datetime.utcnow()
    total = 0
    for Model in (Operation, Export):
        result = await db.execute(
            update(Model)
            .where(Model.status == "running", Model.updated_at < cutoff)
            .values(
                status="failed",
                error_code="SERVER_RESTART",
                error_message="Operation stuck in running state; worker likely crashed",
                completed_at=now,
            )
        )
        total += result.rowcount or 0
    await db.commit()
    if total:
        logger.info("API recovery: marked %d stale running job(s) as failed", total)
    return total
