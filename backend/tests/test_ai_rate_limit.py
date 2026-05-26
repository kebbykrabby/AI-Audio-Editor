"""Unit tests for the per-user AI quota check.

Seeds `operations` rows directly and calls `enforce_ai_quota`. Verifies hourly
and daily bounds, and that non-AI op types do not count.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest


async def _mk_user(db) -> str:
    from app.models.user import User
    u = User(email=f"u-{uuid.uuid4().hex}@example.com")
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u.id


async def _mk_asset(db, user_id: str) -> str:
    from app.models.asset import Asset
    a = Asset(user_id=user_id, type="original", status="ready")
    db.add(a)
    await db.commit()
    await db.refresh(a)
    return a.id


async def _seed_ops(db, user_id: str, asset_id: str, n: int, *, op_type: str, age: timedelta):
    from app.models.operation import Operation
    now = datetime.utcnow()
    created_at = now - age
    for _ in range(n):
        db.add(Operation(
            user_id=user_id,
            type=op_type,
            input_asset_id=asset_id,
            status="completed",
            created_at=created_at,
            queued_at=created_at,
            updated_at=created_at,
        ))
    await db.commit()


async def test_empty_history_ok(db):
    from app.services.ai_quota import enforce_ai_quota
    uid = await _mk_user(db)
    await enforce_ai_quota(db, uid)  # no raise


async def test_at_hourly_limit_blocks(db):
    from app.services.ai_quota import AIQuotaError, enforce_ai_quota
    from app.config import settings
    uid = await _mk_user(db)
    aid = await _mk_asset(db, uid)
    await _seed_ops(
        db, uid, aid, settings.AI_OPS_PER_HOUR_PER_USER,
        op_type="ai_detect_fillers", age=timedelta(minutes=10),
    )
    with pytest.raises(AIQuotaError) as exc:
        await enforce_ai_quota(db, uid)
    assert exc.value.code == "AI_RATE_LIMITED"


async def test_old_ops_do_not_count_against_hour(db):
    from app.services.ai_quota import enforce_ai_quota
    from app.config import settings
    uid = await _mk_user(db)
    aid = await _mk_asset(db, uid)
    # Many ops but all > 1 hour old → hourly window excludes them.
    await _seed_ops(
        db, uid, aid, settings.AI_OPS_PER_HOUR_PER_USER + 5,
        op_type="ai_detect_fillers", age=timedelta(hours=2),
    )
    # Daily window still catches them; verify that instead.
    from app.services.ai_quota import AIQuotaError
    if settings.AI_OPS_PER_HOUR_PER_USER + 5 >= settings.AI_OPS_PER_DAY_PER_USER:
        with pytest.raises(AIQuotaError):
            await enforce_ai_quota(db, uid)
    else:
        await enforce_ai_quota(db, uid)


async def test_daily_limit_blocks(db):
    from app.services.ai_quota import AIQuotaError, enforce_ai_quota
    from app.config import settings
    uid = await _mk_user(db)
    aid = await _mk_asset(db, uid)
    # Spread ops across the day so hourly window sees ≤ HOURLY
    per_hour = max(settings.AI_OPS_PER_HOUR_PER_USER - 1, 1)
    await _seed_ops(
        db, uid, aid, per_hour, op_type="ai_detect_fillers", age=timedelta(minutes=30),
    )
    remaining = settings.AI_OPS_PER_DAY_PER_USER - per_hour
    await _seed_ops(
        db, uid, aid, remaining, op_type="ai_detect_fillers", age=timedelta(hours=6),
    )
    with pytest.raises(AIQuotaError) as exc:
        await enforce_ai_quota(db, uid)
    assert exc.value.code == "AI_RATE_LIMITED"


async def test_non_ai_ops_are_ignored(db):
    from app.services.ai_quota import enforce_ai_quota
    from app.config import settings
    uid = await _mk_user(db)
    aid = await _mk_asset(db, uid)
    # Way over any AI limit — but all `trim`, not an AI op type.
    await _seed_ops(
        db, uid, aid, settings.AI_OPS_PER_DAY_PER_USER + 5,
        op_type="trim", age=timedelta(minutes=5),
    )
    await enforce_ai_quota(db, uid)  # no raise


async def test_other_user_ops_do_not_count(db):
    from app.services.ai_quota import enforce_ai_quota
    from app.config import settings
    user_a = await _mk_user(db)
    user_b = await _mk_user(db)
    asset_b = await _mk_asset(db, user_b)
    await _seed_ops(
        db, user_b, asset_b, settings.AI_OPS_PER_DAY_PER_USER + 5,
        op_type="ai_detect_fillers", age=timedelta(minutes=5),
    )
    await enforce_ai_quota(db, user_a)  # user A is still clean
