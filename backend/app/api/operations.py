from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.asset import AssetResponse
from app.schemas.operation import OperationRequest, OperationResponse
from app.services.operation_service import OperationError, execute_operation
from app.storage.local import storage

router = APIRouter(tags=["operations"])


@router.post("/assets/{asset_id}/operations", response_model=OperationResponse)
async def run_operation(asset_id: str, body: OperationRequest, db: AsyncSession = Depends(get_db)):
    try:
        operation, output_asset, secondary_asset = await execute_operation(
            db,
            op_type=body.type,
            input_asset_id=asset_id,
            parameters=body.parameters.model_dump(),
        )
    except OperationError as e:
        status_map = {
            "ASSET_NOT_FOUND": 404,
            "ASSET_NOT_READY": 409,
            "INVALID_OPERATION": 422,
            "INVALID_PARAMETERS": 422,
            "PROCESSING_TIMEOUT": 504,
            "PROCESSING_FAILED": 500,
        }
        status = status_map.get(e.code, 500)
        content = {"error": {"code": e.code, "message": e.message}}
        if e.field:
            content["error"]["details"] = {"field": e.field}
        return JSONResponse(status_code=status, content=content)

    def _asset_response(a) -> AssetResponse:
        return AssetResponse(
            assetId=a.id,
            type=a.type,
            status=a.status,
            parentAssetId=a.parent_asset_id,
            audioUrl=storage.audio_url(a.id),
            waveformUrl=storage.waveform_url(a.id),
            durationSec=a.duration_sec,
            sampleRate=a.sample_rate,
            channels=a.channels,
        )

    return OperationResponse(
        operationId=operation.id,
        status=operation.status,
        warning=operation.warning,
        asset=_asset_response(output_asset),
        secondaryAsset=_asset_response(secondary_asset) if secondary_asset else None,
    )
