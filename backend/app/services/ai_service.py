"""AI operation orchestration.

Two surfaces:
- **API side** (async SQLAlchemy): admission-time validation + quota check +
  enqueue via Dramatiq. Same contract shape as `operation_service`.
- **Worker side** (sync SQLAlchemy): download input, call provider, run
  classifier, persist `FillerDetectionResult` onto `Operation.result`,
  terminal-state the row.

Provider selection is a module-level factory driven by
`settings.TRANSCRIPTION_PROVIDER`; singleton per worker process so the local
Whisper model stays loaded across operations.
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.config import settings
from app.core.errors import DomainError
from app.models.asset import Asset
from app.models.operation import Operation
from app.models.user import User
from app.processors.filler_detector import detect_fillers
from app.providers.fake import FakeTranscriptionProvider
from app.providers.transcription import (
    TranscriptionError,
    TranscriptionProvider,
)
from app.schemas.ai import FillerDetectionResult, FillerRegionPayload
from app.services import analyses_service
from app.services.ai_quota import enforce_ai_quota
from app.services.operation_service import OperationError
from app.storage import get_storage
from app.storage.base import ObjectNotFound
from app.workers.recovery import worker_id

logger = logging.getLogger(__name__)


# --- Provider factory (singleton per process) --------------------------------

_provider: TranscriptionProvider | None = None


def get_transcription_provider() -> TranscriptionProvider:
    """Cache the provider so the local Whisper model isn't reloaded per call."""
    global _provider
    if _provider is not None:
        return _provider

    name = settings.TRANSCRIPTION_PROVIDER
    if name == "fake":
        _provider = FakeTranscriptionProvider()
    elif name == "local":
        from app.providers.local_whisper import LocalWhisperProvider
        _provider = LocalWhisperProvider(
            model_size=settings.WHISPER_LOCAL_MODEL,
            device=settings.WHISPER_LOCAL_DEVICE,
            compute_type=settings.WHISPER_LOCAL_COMPUTE_TYPE,
        )
    elif name == "openai":
        from app.providers.whisper import WhisperProvider
        _provider = WhisperProvider(
            api_key=settings.OPENAI_API_KEY or "",
            model=settings.WHISPER_MODEL,
        )
    else:
        raise TranscriptionError(
            "provider_unavailable", f"Unknown TRANSCRIPTION_PROVIDER: {name}",
        )
    return _provider


def reset_transcription_provider() -> None:
    """Test hook: clear the cached provider so fixtures can re-inject."""
    global _provider
    _provider = None


# --- Error code translation --------------------------------------------------

_KIND_TO_CODE = {
    "unauthorized": "AI_PROVIDER_UNAVAILABLE",
    "provider_unavailable": "AI_PROVIDER_UNAVAILABLE",
    "rate_limited": "AI_RATE_LIMITED",
    "input_too_long": "AI_INPUT_TOO_LONG",
    "output_invalid": "AI_OUTPUT_INVALID",
}


def _error_code_for(kind: str) -> str:
    return _KIND_TO_CODE.get(kind, "AI_PROVIDER_UNAVAILABLE")


# --- API side ----------------------------------------------------------------


async def enqueue_detect_fillers(
    db: AsyncSession,
    user: User,
    asset_id: str,
    confidence_threshold: float,
    categories: list[str] | None,
) -> Operation:
    asset = await db.get(Asset, asset_id)
    if asset is None or asset.user_id != user.id:
        raise OperationError("ASSET_NOT_FOUND", f"Asset {asset_id} not found")
    if asset.status != "ready":
        raise OperationError("ASSET_NOT_READY", f"Asset {asset_id} is not ready")

    duration = asset.duration_sec or 0.0
    if duration > settings.AI_MAX_INPUT_DURATION_SEC:
        raise OperationError(
            "AI_INPUT_TOO_LONG",
            f"Audio is {duration:.0f}s; max for AI is {settings.AI_MAX_INPUT_DURATION_SEC}s",
            field="duration_sec",
            constraint=f"must be <= {settings.AI_MAX_INPUT_DURATION_SEC}",
            received=duration,
        )
    if asset.file_size_bytes and asset.file_size_bytes > settings.AI_MAX_INPUT_SIZE_MB * 1024 * 1024:
        raise OperationError(
            "AI_INPUT_TOO_LONG",
            f"File exceeds AI size limit of {settings.AI_MAX_INPUT_SIZE_MB} MB",
            field="file_size_bytes",
            constraint=f"must be <= {settings.AI_MAX_INPUT_SIZE_MB} MB",
            received=asset.file_size_bytes,
        )

    # Quota gate. Raises AIQuotaError(DomainError) → translated by the router.
    await enforce_ai_quota(db, user.id)

    operation = Operation(
        user_id=user.id,
        type="ai_detect_fillers",
        input_asset_id=asset_id,
        parameters={
            "confidence_threshold": confidence_threshold,
            "categories": categories,
        },
        status="queued",
    )
    db.add(operation)
    await db.commit()
    await db.refresh(operation)

    from app.workers.ai_worker import run_ai_detect_fillers_actor
    run_ai_detect_fillers_actor.send(operation.id)

    return operation


# --- Worker side -------------------------------------------------------------


def run_ai_detect_fillers_job(db: Session, operation_id: str) -> None:
    asyncio.run(_run_ai_detect_fillers_job_async(db, operation_id))


async def _run_ai_detect_fillers_job_async(db: Session, operation_id: str) -> None:
    now = datetime.utcnow()
    wid = worker_id()
    res = db.execute(
        update(Operation)
        .where(
            Operation.id == operation_id,
            Operation.status.in_(["queued", "running"]),
        )
        .values(
            status="running",
            started_at=now,
            worker_id=wid,
            attempt_count=Operation.attempt_count + 1,
            updated_at=now,
        )
    )
    db.commit()
    if (res.rowcount or 0) == 0:
        logger.info("AI op %s already in terminal state; skipping", operation_id)
        return

    op = db.get(Operation, operation_id)
    if op is None:
        return

    storage = get_storage()
    work_dir = Path(tempfile.mkdtemp(prefix=f"ai_{operation_id[:8]}_"))
    try:
        asset = db.get(Asset, op.input_asset_id)
        if asset is None or asset.storage_key is None:
            raise OperationError("ASSET_NOT_FOUND", "Input asset or storage key missing")

        ext = Path(asset.storage_key).suffix or ".wav"
        input_path = work_dir / f"input{ext}"
        try:
            await storage.download_to_path(asset.storage_key, input_path)
        except ObjectNotFound:
            raise OperationError("PROCESSING_FAILED", "Input audio missing in storage")

        provider = get_transcription_provider()
        analysis_row, transcript = await analyses_service.get_or_create_transcript(
            db, storage, asset, input_path, provider, language="en", tmp_dir=work_dir,
        )

        if transcript.duration_sec > 10 and not transcript.words:
            raise OperationError(
                "AI_NO_SPEECH_DETECTED",
                "No speech detected in the audio",
            )

        params = op.parameters or {}
        threshold = float(params.get("confidence_threshold", 0.0))
        cat_list = params.get("categories")
        cats = frozenset(cat_list) if cat_list else None
        regions = detect_fillers(
            transcript, confidence_threshold=threshold, categories=cats,
        )

        result = FillerDetectionResult(
            transcriptId=analysis_row.id,
            durationSec=transcript.duration_sec,
            language=transcript.language,
            regions=[
                FillerRegionPayload(
                    start=r.start, end=r.end, text=r.text,
                    category=r.category, confidence=r.confidence,
                    wordIndex=r.word_index,
                ) for r in regions
            ],
            costUsd=float(transcript.cost_usd) if transcript.cost_usd is not None else None,
            modelVersion=transcript.model_version,
        )

        op.result = result.model_dump()
        op.cost_usd = transcript.cost_usd
        op.status = "completed"
        op.completed_at = datetime.utcnow()
        op.updated_at = op.completed_at
        db.commit()

        logger.info(
            "ai_detect_fillers done op=%s user=%s duration=%.1fs regions=%d cost=%s model=%s",
            operation_id, op.user_id, transcript.duration_sec,
            len(regions), transcript.cost_usd, transcript.model_version,
        )
    except TranscriptionError as e:
        db.rollback()
        op = db.get(Operation, operation_id)
        if op is not None:
            op.status = "failed"
            op.error_code = _error_code_for(e.kind)
            op.error_message = str(e)[:500]
            op.completed_at = datetime.utcnow()
            op.updated_at = op.completed_at
            db.commit()
    except OperationError as e:
        db.rollback()
        op = db.get(Operation, operation_id)
        if op is not None:
            op.status = "failed"
            op.error_code = e.code
            op.error_message = e.message[:500]
            op.completed_at = datetime.utcnow()
            op.updated_at = op.completed_at
            db.commit()
    except DomainError as e:
        db.rollback()
        op = db.get(Operation, operation_id)
        if op is not None:
            op.status = "failed"
            op.error_code = e.code
            op.error_message = e.message[:500]
            op.completed_at = datetime.utcnow()
            op.updated_at = op.completed_at
            db.commit()
    except Exception as e:
        db.rollback()
        logger.exception("AI op %s crashed", operation_id)
        op = db.get(Operation, operation_id)
        if op is not None:
            op.status = "failed"
            op.error_code = "PROCESSING_FAILED"
            op.error_message = str(e)[:500]
            op.completed_at = datetime.utcnow()
            op.updated_at = op.completed_at
            db.commit()
        raise  # surface to Dramatiq so transient errors are retried
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
