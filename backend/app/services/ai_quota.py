"""Per-user admission-time rate limits for AI operations.

Uses a DB-based sliding-window pattern:
count recent rows in the relevant table (here, `operations`) within a sliding
window. The `ix_operations_user_created` index makes this a cheap lookup even
for users with thousands of ops.

Call `enforce_ai_quota` at the API admission boundary BEFORE creating the
Operation row — a rejected admission must not count against the user's own
quota.

Per-IP limit is deferred to v1.1 (requires adding `ip_address` to `operations`).
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.errors import DomainError
from app.models.operation import Operation


# Operation types that count against the AI quota. Extend as new AI ops ship.
AI_OP_TYPES: frozenset[str] = frozenset({"ai_detect_fillers"})


class AIQuotaError(DomainError):
    pass


async def _count_recent(db: AsyncSession, user_id: str, window: timedelta) -> int:
    since = datetime.utcnow() - window
    res = await db.execute(
        select(func.count())
        .select_from(Operation)
        .where(
            Operation.user_id == user_id,
            Operation.type.in_(AI_OP_TYPES),
            Operation.created_at >= since,
        )
    )
    return int(res.scalar_one() or 0)


async def enforce_ai_quota(db: AsyncSession, user_id: str) -> None:
    per_hour = await _count_recent(db, user_id, timedelta(hours=1))
    if per_hour >= settings.AI_OPS_PER_HOUR_PER_USER:
        raise AIQuotaError(
            "AI_RATE_LIMITED",
            f"Hourly AI limit reached ({settings.AI_OPS_PER_HOUR_PER_USER}/hr); try again shortly",
        )

    per_day = await _count_recent(db, user_id, timedelta(days=1))
    if per_day >= settings.AI_OPS_PER_DAY_PER_USER:
        raise AIQuotaError(
            "AI_RATE_LIMITED",
            f"Daily AI limit reached ({settings.AI_OPS_PER_DAY_PER_USER}/day); try again tomorrow",
        )
