import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session, get_db
from app.schemas.asset import AssetResponse, UploadResponse
from app.services import asset_service
from app.storage.local import storage

router = APIRouter(prefix="/assets", tags=["assets"])

ALLOWED_EXTENSIONS = {".wav", ".mp3"}
MAX_SIZE_BYTES = 100 * 1024 * 1024  # 100MB


@router.post("/upload", status_code=202, response_model=UploadResponse)
async def upload_audio(file: UploadFile, db: AsyncSession = Depends(get_db)):
    # Validate extension
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return JSONResponse(status_code=422, content={
            "error": {"code": "INVALID_FILE", "message": f"Unsupported format: {ext}. Accepted: WAV, MP3"}
        })

    # Validate size (Content-Length header)
    if file.size and file.size > MAX_SIZE_BYTES:
        return JSONResponse(status_code=422, content={
            "error": {"code": "INVALID_FILE", "message": "File exceeds 100MB limit"}
        })

    # Create asset record
    asset = await asset_service.create_upload_asset(db, file.filename or "audio")

    # Save file
    await storage.save_upload(asset.id, file)

    # Launch background processing
    asyncio.create_task(asset_service.process_upload(asset.id, async_session))

    return UploadResponse(assetId=asset.id, status="processing")


@router.get("/{asset_id}", response_model=AssetResponse)
async def get_asset(asset_id: str, db: AsyncSession = Depends(get_db)):
    asset = await asset_service.get_asset(db, asset_id)
    if not asset:
        return JSONResponse(status_code=404, content={
            "error": {"code": "ASSET_NOT_FOUND", "message": f"Asset {asset_id} not found"}
        })

    response = AssetResponse(
        assetId=asset.id,
        type=asset.type,
        status=asset.status,
        parentAssetId=asset.parent_asset_id,
        audioUrl=storage.audio_url(asset.id) if asset.status == "ready" else None,
        waveformUrl=storage.waveform_url(asset.id) if asset.status == "ready" else None,
        durationSec=asset.duration_sec,
        sampleRate=asset.sample_rate,
        channels=asset.channels,
    )

    if asset.status == "failed" and asset.error_code:
        response.error = {"code": asset.error_code, "message": asset.error_message or "Unknown error"}

    headers = {}
    if asset.status == "processing":
        headers["Retry-After"] = "2"

    return JSONResponse(content=response.model_dump(), headers=headers)


@router.get("/{asset_id}/audio")
async def stream_audio(asset_id: str, db: AsyncSession = Depends(get_db)):
    asset = await asset_service.get_asset(db, asset_id)
    if not asset or asset.status != "ready":
        raise HTTPException(status_code=404, detail="Asset not found or not ready")

    audio_path = storage.get_audio_path(asset_id)
    if not audio_path or not audio_path.exists():
        audio_path = storage.get_original_path(asset_id)
    if not audio_path or not audio_path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found")

    media_type = "audio/wav" if audio_path.suffix == ".wav" else "audio/mpeg"
    return FileResponse(
        path=str(audio_path),
        media_type=media_type,
        filename=audio_path.name,
    )
