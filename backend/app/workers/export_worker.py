import logging

import dramatiq

from app.config import settings
from app.workers.broker import broker  # noqa: F401
from app.workers.db import SyncSession

logger = logging.getLogger(__name__)


@dramatiq.actor(
    queue_name="exports",
    max_retries=2,
    min_backoff=2_000,
    max_backoff=30_000,
    time_limit=settings.WORKER_TIME_LIMIT_SEC * 1000,
)
def run_export_actor(export_id: str) -> None:
    from app.services.export_service import run_export_job

    with SyncSession() as db:
        run_export_job(db, export_id)
