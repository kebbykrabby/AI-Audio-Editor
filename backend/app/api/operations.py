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
        operation, output_asset = await execute_operation(
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

    return OperationResponse(
        operationId=operation.id,
        status=operation.status,
        warning=operation.warning,
        asset=AssetResponse(
            assetId=output_asset.id,
            type=output_asset.type,
            status=output_asset.status,
            parentAssetId=output_asset.parent_asset_id,
            audioUrl=storage.audio_url(output_asset.id),
            waveformUrl=storage.waveform_url(output_asset.id),
            durationSec=output_asset.duration_sec,
            sampleRate=output_asset.sample_rate,
            channels=output_asset.channels,
        ),
    )
