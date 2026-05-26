import logging
import os
import threading
import time

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


class HeartbeatMiddleware(dramatiq.Middleware):
    """Periodic liveness log so a frozen worker is visible in the log tail.

    Dramatiq already prints per-message lines; a stuck worker goes silent.
    This daemon thread emits one line every `interval_sec` with the queues
    the process is consuming — enough signal for `docker logs -f` or a
    shell tail to catch a hang.
    """

    def __init__(self, interval_sec: int = 60) -> None:
        self._interval = interval_sec
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._queues: tuple[str, ...] = ()

    def before_worker_boot(self, broker, worker) -> None:
        self._queues = tuple(sorted(getattr(worker, "queues", {}).keys())) or ("default",)
        self._stop.clear()
        t = threading.Thread(
            target=self._loop, name="worker-heartbeat", daemon=True,
        )
        self._thread = t
        t.start()
        logger.info("worker alive queues=%s pid=%s", list(self._queues), os.getpid())

    def after_worker_shutdown(self, broker, worker) -> None:
        self._stop.set()

    def _loop(self) -> None:
        # Deliberately a plain sleep loop (not `Event.wait` in a tight range)
        # because Dramatiq's per-message log gives us sub-interval liveness
        # under load — the heartbeat only matters when the worker is idle.
        while not self._stop.is_set():
            if self._stop.wait(self._interval):
                return
            logger.info("worker alive queues=%s pid=%s", list(self._queues), os.getpid())


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
    broker.add_middleware(HeartbeatMiddleware())
    return broker


def _should_retry(retries_so_far: int, exception: BaseException) -> bool:
    if isinstance(exception, DomainError):
        return False
    return retries_so_far < 2


broker = _build_broker()
dramatiq.set_broker(broker)
