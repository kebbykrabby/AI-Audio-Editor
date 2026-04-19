from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.export import ExportRequest, ExportResponse
from app.services import export_service
from app.services.export_service import ExportError

router = APIRouter(tags=["exports"])


@router.post(
    "/assets/{asset_id}/export",
    response_model=ExportResponse,
    status_code=202,
)
async def enqueue_export(
    asset_id: str,
    body: ExportRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        export = await export_service.enqueue_export(
            db,
            user=user,
            asset_id=asset_id,
            fmt=body.format,
            sample_rate=body.sample_rate,
            bitrate_kbps=body.bitrate_kbps,
        )
    except ExportError as e:
        status_map = {
            "ASSET_NOT_FOUND": 404,
            "ASSET_NOT_READY": 409,
        }
        return JSONResponse(
            status_code=status_map.get(e.code, 500),
            content={"error": {"code": e.code, "message": e.message}},
        )

    return ExportResponse(
        exportId=export.id,
        status=export.status,
        format=export.format,
        sampleRate=export.sample_rate,
        bitrateKbps=export.bitrate_kbps,
        channels=None,
        downloadUrl=None,
        error=None,
    )


@router.get(
    "/exports/{export_id}",
    response_model=ExportResponse,
)
async def get_export(
    export_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    exp = await export_service.get_export_for_user(db, export_id, user.id)
    if exp is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "code": "EXPORT_NOT_FOUND",
                    "message": f"Export {export_id} not found",
                }
            },
        )

    response = await export_service.build_export_response(db, exp)
    payload = response.model_dump()
    for k in ("downloadUrl", "error", "sampleRate", "bitrateKbps", "channels"):
        if payload.get(k) is None:
            payload.pop(k, None)

    headers = {"Retry-After": "2"} if exp.status in ("queued", "running") else {}
    return JSONResponse(content=payload, headers=headers)
