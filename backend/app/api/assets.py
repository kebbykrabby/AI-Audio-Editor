from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.asset import AssetResponse, UploadResponse
from app.services import asset_service
from app.services.asset_service import AssetError

router = APIRouter(prefix="/assets", tags=["assets"])


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
