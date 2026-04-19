import logging
import os

import dramatiq
from dramatiq.brokers.redis import RedisBroker
from dramatiq.brokers.stub import StubBroker
from dramatiq.middleware import AgeLimit, Callbacks, Pipelines, Retries, ShutdownNotifications

from app.config import settings
from app.core.errors import DomainError

logger = logging.getLogger(__name__)


class WorkerRecoveryMiddleware(dramatiq.Middleware):
    """On worker process boot, mark any DB rows this worker owned as failed.

    Same host:pid starting up means the previous instance on this slot
    died mid-job; that job cannot resume safely and is marked failed.
    """

    def before_worker_boot(self, broker, worker) -> None:
        from app.workers.db import SyncSession
        from app.workers.recovery import recover_orphaned_for_this_worker

        try:
            with SyncSession() as db:
                recover_orphaned_for_this_worker(db)
        except Exception:
            logger.exception("Worker recovery sweep failed during boot")


def _build_broker() -> dramatiq.Broker:
    # Under pytest: use StubBroker so actor registration + .send()/.join() work
    # without Redis. The WorkerRecoveryMiddleware still runs if a Worker is
    # started in-test (for recovery-path tests); otherwise it's inert.
    if os.getenv("TESTING") == "1":
        broker = StubBroker()
        broker.add_middleware(WorkerRecoveryMiddleware())
        return broker

    broker = RedisBroker(url=settings.REDIS_URL)

    broker.middleware = [m for m in broker.middleware if not isinstance(m, (Retries, AgeLimit))]

    broker.add_middleware(AgeLimit(max_age=settings.WORKER_AGE_LIMIT_SEC * 1000))
    broker.add_middleware(
        Retries(
            max_retries=2,
            min_backoff=2_000,
            max_backoff=30_000,
            retry_when=_should_retry,
        )
    )
    if not any(isinstance(m, Callbacks) for m in broker.middleware):
        broker.add_middleware(Callbacks())
    if not any(isinstance(m, Pipelines) for m in broker.middleware):
        broker.add_middleware(Pipelines())
    if not any(isinstance(m, ShutdownNotifications) for m in broker.middleware):
        broker.add_middleware(ShutdownNotifications())

    broker.add_middleware(WorkerRecoveryMiddleware())
    return broker


def _should_retry(retries_so_far: int, exception: BaseException) -> bool:
    if isinstance(exception, DomainError):
        return False
    return retries_so_far < 2


broker = _build_broker()
dramatiq.set_broker(broker)
