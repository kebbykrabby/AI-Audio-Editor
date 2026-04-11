import asyncio
import logging
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset
from app.processors import ffmpeg as ffmpeg_proc
from app.processors.waveform import generate_waveform
from app.storage.local import storage

logger = logging.getLogger(__name__)


def _new_asset_id() -> str:
    return f"ast_{uuid.uuid4().hex[:12]}"


async def create_upload_asset(db: AsyncSession, filename: str) -> Asset:
    asset = Asset(
        id=_new_asset_id(),
        type="original",
        status="processing",
        filename=filename,
    )
    db.add(asset)
    await db.commit()
    await db.refresh(asset)
    return asset


async def process_upload(asset_id: str, db_factory) -> None:
    """Background task: probe, generate waveform, update DB."""
    async with db_factory() as db:
        asset = await db.get(Asset, asset_id)
        if not asset:
            return
        try:
            original = storage.get_original_path(asset_id)
            if not original:
                raise RuntimeError("Original file not found")

            # Probe audio metadata
            info = await ffmpeg_proc.probe_audio(original)

            # Generate waveform
            await generate_waveform(original)

            # Update asset
            asset.duration_sec = info["duration_sec"]
            asset.sample_rate = info["sample_rate"]
            asset.channels = info["channels"]
            asset.status = "ready"
            await db.commit()

        except Exception as e:
            logger.exception("Upload processing failed for %s", asset_id)
            asset.status = "failed"
            asset.error_code = "PROCESSING_FAILED"
            asset.error_message = str(e)[:500]
            await db.commit()


async def get_asset(db: AsyncSession, asset_id: str) -> Asset | None:
    return await db.get(Asset, asset_id)
