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
from app.models.export import Export
from app.models.user import User
from app.processors import ffmpeg as ffmpeg_proc
from app.schemas.error import ErrorBody
from app.schemas.export import ExportResponse
from app.storage import get_storage
from app.storage.base import ObjectNotFound
from app.workers.recovery import worker_id

logger = logging.getLogger(__name__)


class ExportError(DomainError):
    pass


def _export_key(user_id: str, export_id: str, fmt: str) -> str:
    return f"users/{user_id}/exports/{export_id}/out.{fmt}"


def _download_filename(asset: Asset, fmt: str) -> str:
    stem = Path(asset.filename or "audio").stem or "audio"
    return f"{stem}.{fmt}"


# ---------- API side (async) ----------


async def enqueue_export(
    db: AsyncSession,
    user: User,
    asset_id: str,
    fmt: str,
    sample_rate: int | None,
    bitrate_kbps: int | None,
) -> Export:
    asset = await db.get(Asset, asset_id)
    if asset is None or asset.user_id != user.id:
        raise ExportError("ASSET_NOT_FOUND", f"Asset {asset_id} not found")
    if asset.status != "ready":
        raise ExportError("ASSET_NOT_READY", f"Asset {asset_id} is not ready")

    export = Export(
        user_id=user.id,
        source_asset_id=asset_id,
        format=fmt,
        sample_rate=sample_rate,
        bitrate_kbps=bitrate_kbps,
        status="queued",
    )
    db.add(export)
    await db.commit()
    await db.refresh(export)

    from app.workers.export_worker import run_export_actor
    run_export_actor.send(export.id)

    return export


async def get_export_for_user(
    db: AsyncSession, export_id: str, user_id: str
) -> Export | None:
    exp = await db.get(Export, export_id)
    if exp is None or exp.user_id != user_id:
        return None
    return exp


async def build_export_response(
    db: AsyncSession, exp: Export
) -> ExportResponse:
    download_url: str | None = None
    channels: int | None = None

    source = await db.get(Asset, exp.source_asset_id) if exp.source_asset_id else None
    if source is not None:
        channels = source.channels

    if exp.status == "completed" and exp.storage_key:
        storage = get_storage()
        filename = _download_filename(source, exp.format) if source else f"export.{exp.format}"
        download_url = await storage.signed_url(
            exp.storage_key,
            expires_in_sec=settings.SIGNED_URL_TTL_SEC,
            download_name=filename,
        )

    error = None
    if exp.status == "failed" and exp.error_code:
        error = ErrorBody(code=exp.error_code, message=exp.error_message or "Export failed")

    return ExportResponse(
        exportId=exp.id,
        status=exp.status,
        format=exp.format,
        sampleRate=exp.sample_rate,
        bitrateKbps=exp.bitrate_kbps,
        channels=channels,
        downloadUrl=download_url,
        error=error,
    )


# ---------- Worker side (sync) ----------


def run_export_job(db: Session, export_id: str) -> None:
    asyncio.run(_run_export_job_async(db, export_id))


async def _run_export_job_async(db: Session, export_id: str) -> None:
    now = datetime.utcnow()
    wid = worker_id()
    res = db.execute(
        update(Export)
        .where(Export.id == export_id, Export.status.in_(["queued", "running"]))
        .values(
            status="running",
            started_at=now,
            worker_id=wid,
            attempt_count=Export.attempt_count + 1,
            updated_at=now,
        )
    )
    db.commit()
    if (res.rowcount or 0) == 0:
        return

    exp = db.get(Export, export_id)
    if exp is None:
        return

    storage = get_storage()
    work_dir = Path(tempfile.mkdtemp(prefix=f"exp_{export_id[:8]}_"))
    try:
        asset = db.get(Asset, exp.source_asset_id)
        if asset is None:
            raise ExportError("ASSET_NOT_FOUND", "Source asset not found")
        if asset.storage_key is None:
            raise ExportError("ASSET_NOT_READY", "Source asset has no storage key")

        ext = Path(asset.storage_key).suffix or ".wav"
        input_path = work_dir / f"input{ext}"
        try:
            await storage.download_to_path(asset.storage_key, input_path)
        except ObjectNotFound:
            raise ExportError("PROCESSING_FAILED", "Source audio missing in storage")

        output_path = work_dir / f"out.{exp.format}"
        try:
            await ffmpeg_proc.export_audio(
                input_path, output_path, exp.format, exp.sample_rate, exp.bitrate_kbps
            )
        except RuntimeError as e:
            raise ExportError("EXPORT_FAILED", f"Encoding failed: {str(e)[:200]}")

        key = _export_key(exp.user_id, exp.id, exp.format)
        content_type = "audio/mpeg" if exp.format == "mp3" else "audio/wav"
        await storage.put_file(key, output_path, content_type)

        exp.storage_key = key
        exp.status = "completed"
        exp.completed_at = datetime.utcnow()
        exp.updated_at = exp.completed_at
        db.commit()
    except DomainError as e:
        db.rollback()
        exp = db.get(Export, export_id)
        if exp is not None:
            exp.status = "failed"
            exp.error_code = e.code
            exp.error_message = e.message[:500]
            exp.completed_at = datetime.utcnow()
            exp.updated_at = exp.completed_at
            db.commit()
    except Exception as e:
        db.rollback()
        logger.exception("Export %s crashed", export_id)
        exp = db.get(Export, export_id)
        if exp is not None:
            exp.status = "failed"
            exp.error_code = "EXPORT_FAILED"
            exp.error_message = str(e)[:500]
            exp.completed_at = datetime.utcnow()
            exp.updated_at = exp.completed_at
            db.commit()
        raise
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
