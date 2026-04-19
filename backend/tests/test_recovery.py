"""Startup recovery sweeps for orphaned operations/exports.

Covers:
- worker startup: rows owned by this worker_id in status='running' flip to
  'failed' with error_code='SERVER_RESTART'.
- API startup: rows in status='running' older than WORKER_STALE_RUNNING_MIN
  flip to 'failed' regardless of worker_id.
- API startup: fresh 'running' rows (younger than threshold) are untouched —
  guards against killing legitimately-running jobs.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture()
async def seeded_user_and_asset(db):
    """Insert a user and a ready asset directly — no HTTP."""
    from app.models.asset import Asset
    from app.models.user import User

    user = User(email="recovery-test@example.com")
    db.add(user)
    await db.flush()

    asset = Asset(
        user_id=user.id,
        type="original",
        status="ready",
        filename="recovery.wav",
        mime_type="audio/wav",
        storage_key=f"users/{user.id}/assets/placeholder/audio.wav",
        duration_sec=1.0,
        sample_rate=44100,
        channels=2,
    )
    db.add(asset)
    await db.commit()
    return user, asset


async def _insert_running_op(db, user_id, asset_id, *, worker_id: str, updated_at: datetime):
    from app.models.operation import Operation

    op = Operation(
        user_id=user_id,
        type="trim",
        input_asset_id=asset_id,
        parameters={"start_sec": 0.1, "end_sec": 0.5},
        status="running",
        worker_id=worker_id,
        queued_at=updated_at,
        started_at=updated_at,
        created_at=updated_at,
        updated_at=updated_at,
    )
    db.add(op)
    await db.commit()
    await db.refresh(op)
    return op


# --- Worker-boot sweep ----------------------------------------------------

async def test_worker_startup_marks_own_running_as_failed(seeded_user_and_asset, db):
    user, asset = seeded_user_and_asset
    from app.workers.db import SyncSession
    from app.workers.recovery import recover_orphaned_for_this_worker, worker_id

    own = worker_id()
    op = await _insert_running_op(
        db, user.id, asset.id, worker_id=own, updated_at=datetime.utcnow(),
    )

    # Sync sweep (simulates the Dramatiq before_worker_boot middleware)
    with SyncSession() as sdb:
        n = recover_orphaned_for_this_worker(sdb)
    assert n >= 1

    # Confirm the row flipped
    from app.models.operation import Operation
    await db.refresh(op)
    fresh = (await db.execute(select(Operation).where(Operation.id == op.id))).scalar_one()
    assert fresh.status == "failed"
    assert fresh.error_code == "SERVER_RESTART"
    assert fresh.completed_at is not None


async def test_worker_startup_leaves_foreign_running_alone(seeded_user_and_asset, db):
    user, asset = seeded_user_and_asset
    from app.workers.db import SyncSession
    from app.workers.recovery import recover_orphaned_for_this_worker

    op = await _insert_running_op(
        db, user.id, asset.id,
        worker_id="some-other-host:99999",
        updated_at=datetime.utcnow(),
    )

    with SyncSession() as sdb:
        recover_orphaned_for_this_worker(sdb)

    from app.models.operation import Operation
    fresh = (await db.execute(select(Operation).where(Operation.id == op.id))).scalar_one()
    assert fresh.status == "running", "worker sweep should not touch foreign worker_id rows"


# --- API-boot sweep -------------------------------------------------------

async def test_api_startup_flips_stale_foreign_running(seeded_user_and_asset, db):
    """A row with a foreign worker_id that hasn't been updated in a long time
    must be marked failed by the API startup sweep."""
    user, asset = seeded_user_and_asset
    from app.config import settings
    from app.workers.recovery import recover_stale_running

    stale = datetime.utcnow() - timedelta(minutes=settings.WORKER_STALE_RUNNING_MIN + 5)
    op = await _insert_running_op(
        db, user.id, asset.id,
        worker_id="ghost-host:99999",
        updated_at=stale,
    )

    n = await recover_stale_running(db)
    assert n >= 1

    from app.models.operation import Operation
    fresh = (await db.execute(select(Operation).where(Operation.id == op.id))).scalar_one()
    assert fresh.status == "failed"
    assert fresh.error_code == "SERVER_RESTART"


async def test_api_startup_leaves_fresh_running_alone(seeded_user_and_asset, db):
    """A row that was updated recently (well within the stale threshold) must
    be untouched — or the sweep would kill legitimately-running jobs."""
    user, asset = seeded_user_and_asset
    from app.workers.recovery import recover_stale_running

    op = await _insert_running_op(
        db, user.id, asset.id,
        worker_id="some-worker:1234",
        updated_at=datetime.utcnow(),  # fresh
    )

    await recover_stale_running(db)

    from app.models.operation import Operation
    fresh = (await db.execute(select(Operation).where(Operation.id == op.id))).scalar_one()
    assert fresh.status == "running", "fresh running rows must survive the sweep"
