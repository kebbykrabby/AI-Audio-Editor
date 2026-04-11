from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.export import ExportRequest, ExportResponse
from app.services.export_service import export_audio
from app.services.operation_service import OperationError

router = APIRouter(tags=["export"])


@router.post("/assets/{asset_id}/export", response_model=ExportResponse)
async def run_export(asset_id: str, body: ExportRequest, db: AsyncSession = Depends(get_db)):
    try:
        result = await export_audio(
            db,
            asset_id=asset_id,
            fmt=body.format,
            sample_rate=body.sample_rate,
            bitrate_kbps=body.bitrate_kbps,
        )
    except OperationError as e:
        status_map = {
            "ASSET_NOT_FOUND": 404,
            "ASSET_NOT_READY": 409,
            "INVALID_PARAMETERS": 422,
            "PROCESSING_FAILED": 500,
            "EXPORT_FAILED": 500,
        }
        return JSONResponse(
            status_code=status_map.get(e.code, 500),
            content={"error": {"code": e.code, "message": e.message}},
        )

    return ExportResponse(**result)
