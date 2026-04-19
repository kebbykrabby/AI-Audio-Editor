import asyncio
import logging
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.errors import DomainError
from app.models.asset import Asset
from app.models.user import User
from app.processors import ffmpeg as ffmpeg_proc
from app.processors.waveform import generate_waveform
from app.schemas.asset import AssetResponse
from app.schemas.error import ErrorBody
from app.storage import Storage, get_storage
from app.storage.base import ObjectNotFound
from app.workers.recovery import worker_id

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {".wav", ".mp3"}


class AssetError(DomainError):
    pass


def _audio_key(user_id: str, asset_id: str, ext: str) -> str:
    return f"users/{user_id}/assets/{asset_id}/audio{ext.lower()}"


def _waveform_key(user_id: str, asset_id: str) -> str:
    return f"users/{user_id}/assets/{asset_id}/waveform.json"


def _content_type_for(ext: str) -> str:
    return "audio/mpeg" if ext.lower() == ".mp3" else "audio/wav"


async def create_upload_asset(
    db: AsyncSession,
    user: User,
    file: UploadFile,
) -> Asset:
    """Validate upload, stream to storage, create Asset row. Returns the row."""
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise AssetError("INVALID_FILE", f"Unsupported format: {ext}. Accepted: WAV, MP3")

    asset = Asset(
        user_id=user.id,
        type="original",
        status="processing",
        filename=(file.filename or "audio")[:255],
        mime_type=_content_type_for(ext),
    )
    db.add(asset)
    await db.flush()  # obtain asset.id

    storage = get_storage()
    key = _audio_key(user.id, asset.id, ext)

    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp_path = Path(tmp.name)
        try:
            total = 0
            while chunk := await file.read(1024 * 1024):
                tmp.write(chunk)
                total += len(chunk)
            tmp.close()
            asset.file_size_bytes = total
            await storage.put_file(key, tmp_path, asset.mime_type or "audio/wav")
            asset.storage_key = key
            await db.commit()
        finally:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass

    return asset


async def get_asset_for_user(
    db: AsyncSession, asset_id: str, user_id: str
) -> Asset | None:
    asset = await db.get(Asset, asset_id)
    if asset is None or asset.user_id != user_id:
        return None
    return asset


async def build_asset_response(asset: Asset, storage: Storage | None = None) -> AssetResponse:
    storage = storage or get_storage()
    audio_url: str | None = None
    waveform_url: str | None = None
    if asset.status == "ready":
        if asset.storage_key:
            audio_url = await storage.signed_url(asset.storage_key, download_name=asset.filename)
        if asset.waveform_key:
            waveform_url = await storage.signed_url(asset.waveform_key)

    error: ErrorBody | None = None
    if asset.status == "failed" and asset.error_code:
        error = ErrorBody(code=asset.error_code, message=asset.error_message or "Processing failed")

    return AssetResponse(
        assetId=asset.id,
        userId=asset.user_id,
        type=asset.type,
        status=asset.status,
        parentAssetId=asset.parent_asset_id,
        audioUrl=audio_url,
        waveformUrl=waveform_url,
        durationSec=asset.duration_sec,
        sampleRate=asset.sample_rate,
        channels=asset.channels,
        filename=asset.filename,
        error=error,
    )


# ---------- Worker side (sync SQLAlchemy) ----------


def run_upload_job(db: Session, asset_id: str) -> None:
    asyncio.run(_run_upload_job_async(db, asset_id))


async def _run_upload_job_async(db: Session, asset_id: str) -> None:
    asset = db.get(Asset, asset_id)
    if asset is None:
        logger.warning("Upload job: asset %s not found", asset_id)
        return
    if asset.status == "ready":
        return
    if asset.storage_key is None:
        _fail_asset(db, asset, "PROCESSING_FAILED", "Upload completed without a storage key")
        return

    storage = get_storage()
    work_dir = Path(tempfile.mkdtemp(prefix=f"upl_{asset_id[:8]}_"))
    try:
        # Optimistic claim to discourage double-run
        asset.status = "processing"
        asset.updated_at = datetime.utcnow()
        db.commit()

        ext = Path(asset.storage_key).suffix.lower() or ".wav"
        local_audio = work_dir / f"input{ext}"
        try:
            await storage.download_to_path(asset.storage_key, local_audio)
        except ObjectNotFound:
            _fail_asset(db, asset, "PROCESSING_FAILED", "Uploaded audio is missing from storage")
            return

        info = await ffmpeg_proc.probe_audio(local_audio)
        await generate_waveform(local_audio)
        wf_local = local_audio.parent / "waveform.json"
        if not wf_local.exists():
            # processors.waveform writes to <input>.waveform.json per convention;
            # guard in case of a different filename scheme.
            possible = list(local_audio.parent.glob("*.json"))
            if possible:
                wf_local = possible[0]
        wf_key = _waveform_key(asset.user_id, asset.id)
        await storage.put_file(wf_key, wf_local, "application/json")

        asset.duration_sec = info["duration_sec"]
        asset.sample_rate = info["sample_rate"]
        asset.channels = info["channels"]
        asset.waveform_key = wf_key
        asset.status = "ready"
        asset.error_code = None
        asset.error_message = None
        asset.updated_at = datetime.utcnow()
        db.commit()
        logger.info("Upload %s ready (worker=%s)", asset_id, worker_id())
    except DomainError as e:
        db.rollback()
        db.refresh(asset)
        _fail_asset(db, asset, e.code, e.message)
    except Exception as e:
        db.rollback()
        db.refresh(asset)
        logger.exception("Upload processing failed for %s", asset_id)
        _fail_asset(db, asset, "PROCESSING_FAILED", str(e)[:500])
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _fail_asset(db: Session, asset: Asset, code: str, message: str) -> None:
    asset.status = "failed"
    asset.error_code = code
    asset.error_message = message[:500]
    asset.updated_at = datetime.utcnow()
    db.commit()
