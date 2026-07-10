from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.asset import (
    AssetListItem,
    AssetListResponse,
    AssetResponse,
    UploadResponse,
)
from app.services import asset_service
from app.services.asset_service import AssetError

router = APIRouter(prefix="/assets", tags=["assets"])


@router.get("", response_model=AssetListResponse)
async def list_assets(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List the current user's original (non-deleted) uploads for the Dashboard."""
    rows = await asset_service.list_user_originals(db, user.id)
    return AssetListResponse(
        assets=[
            AssetListItem(
                assetId=a.id,
                filename=a.filename,
                status=a.status,
                durationSec=a.duration_sec,
                sampleRate=a.sample_rate,
                channels=a.channels,
                fileSizeBytes=a.file_size_bytes,
                createdAt=a.created_at,
                updatedAt=a.updated_at,
            )
            for a in rows
        ]
    )


@router.post("/upload", status_code=202, response_model=UploadResponse)
async def upload_audio(
    file: UploadFile,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        asset = await asset_service.create_upload_asset(db, user, file)
    except AssetError as e:
        raise HTTPException(status_code=422, detail={"code": e.code, "message": e.message})

    from app.workers.upload_worker import run_upload_actor
    run_upload_actor.send(asset.id)

    return UploadResponse(assetId=asset.id, status=asset.status)


@router.get("/{asset_id}", response_model=AssetResponse)
async def get_asset(
    asset_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    asset = await asset_service.get_asset_for_user(db, asset_id, user.id)
    if asset is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"code": "ASSET_NOT_FOUND", "message": f"Asset {asset_id} not found"}},
        )

    response = await asset_service.build_asset_response(asset)
    headers = {"Retry-After": "2"} if asset.status == "processing" else {}

    payload = response.model_dump()
    if payload.get("error") is None:
        payload.pop("error", None)

    return JSONResponse(content=payload, headers=headers)


@router.delete("/{asset_id}", status_code=204)
async def delete_asset(
    asset_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete an asset (Dashboard trash button).

    Idempotent — a repeated DELETE against an already-deleted or unknown asset
    still returns 204, so the Dashboard doesn't need to check first.
    """
    await asset_service.soft_delete_asset(db, asset_id, user.id)
    return Response(status_code=204)
