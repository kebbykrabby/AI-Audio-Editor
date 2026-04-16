from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset
from app.processors import ffmpeg as ffmpeg_proc
from app.services.operation_service import OperationError
from app.storage.local import storage


async def export_audio(
    db: AsyncSession, asset_id: str, fmt: str,
    sample_rate: int | None = None, bitrate_kbps: int | None = None,
) -> dict:
    asset = await db.get(Asset, asset_id)
    if not asset:
        raise OperationError("ASSET_NOT_FOUND", f"Asset {asset_id} not found")
    if asset.status != "ready":
        raise OperationError("ASSET_NOT_READY", f"Asset {asset_id} is not ready")

    input_path = storage.get_audio_path(asset_id)
    if not input_path or not input_path.exists():
        input_path = storage.get_original_path(asset_id)
    if not input_path:
        raise OperationError("PROCESSING_FAILED", "Audio file not found")

    output_path = storage.get_export_path(asset_id, fmt)
    try:
        await ffmpeg_proc.export_audio(input_path, output_path, fmt, sample_rate, bitrate_kbps)
    except RuntimeError as e:
        raise OperationError("EXPORT_FAILED", f"Export encoding failed: {str(e)[:200]}")

    return {
        "downloadUrl": f"/files/{asset_id}/export.{fmt}",
        "format": fmt,
        "sampleRate": sample_rate or asset.sample_rate,
        "channels": asset.channels,
    }
