import logging

import dramatiq

from app.config import settings
from app.workers.broker import broker  # noqa: F401  (ensures broker is registered)
from app.workers.db import SyncSession

logger = logging.getLogger(__name__)


@dramatiq.actor(
    queue_name="operations",
    max_retries=2,
    min_backoff=2_000,
    max_backoff=30_000,
    time_limit=settings.WORKER_TIME_LIMIT_SEC * 1000,
)
def run_operation_actor(operation_id: str) -> None:
    # Lazy import so Phase 6 can fill in run_operation_job without Phase 5
    # needing a matching service rewrite.
    from app.services.operation_service import run_operation_job

    with SyncSession() as db:
        run_operation_job(db, operation_id)
