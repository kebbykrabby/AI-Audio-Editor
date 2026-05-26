"""AI Dramatiq actor — separate `ai` queue so slow transcription never blocks
a deterministic DSP op on the `operations` queue. Launch a dedicated worker:

    dramatiq app.workers.entrypoint -Q ai -p 1 -t 1
"""
import logging

import dramatiq

from app.config import settings
from app.workers.broker import broker  # noqa: F401  (ensures broker is registered)
from app.workers.db import SyncSession

logger = logging.getLogger(__name__)


@dramatiq.actor(
    queue_name="ai",
    max_retries=2,
    min_backoff=2_000,
    max_backoff=30_000,
    time_limit=settings.WORKER_TIME_LIMIT_SEC * 1000,
)
def run_ai_detect_fillers_actor(operation_id: str) -> None:
    from app.services.ai_service import run_ai_detect_fillers_job

    with SyncSession() as db:
        run_ai_detect_fillers_job(db, operation_id)
