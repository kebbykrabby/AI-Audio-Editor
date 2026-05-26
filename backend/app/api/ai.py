"""AI endpoints.

Thin alias over the Operation lifecycle: `POST /api/assets/{id}/ai/detect-fillers`
creates an `ai_detect_fillers` Operation and enqueues the AI worker. Clients
poll the standard `GET /api/operations/{id}` for the `FillerDetectionResult`
on completion. The commit step (`remove_segments`) goes through the existing
`POST /api/assets/{id}/operations` endpoint.
"""
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.ai import DetectFillersRequest
from app.schemas.operation import OperationResponse
from app.services import ai_service
from app.services.ai_quota import AIQuotaError
from app.services.operation_service import OperationError

router = APIRouter(tags=["ai"])


_STATUS_MAP = {
    "ASSET_NOT_FOUND": 404,
    "ASSET_NOT_READY": 409,
    "AI_INPUT_TOO_LONG": 422,
    "AI_QUOTA_EXCEEDED": 422,
    "AI_RATE_LIMITED": 429,
    "INVALID_PARAMETERS": 422,
}


@router.post(
    "/assets/{asset_id}/ai/detect-fillers",
    response_model=OperationResponse,
    status_code=202,
)
async def detect_fillers(
    asset_id: str,
    body: DetectFillersRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        operation = await ai_service.enqueue_detect_fillers(
            db,
            user=user,
            asset_id=asset_id,
            confidence_threshold=body.confidence_threshold,
            categories=body.categories,
        )
    except OperationError as e:
        content: dict = {"error": {"code": e.code, "message": e.message}}
        if e.field:
            details: dict = {"field": e.field}
            if e.constraint:
                details["constraint"] = e.constraint
            if e.received is not None:
                details["received"] = e.received
            content["error"]["details"] = details
        return JSONResponse(status_code=_STATUS_MAP.get(e.code, 500), content=content)
    except AIQuotaError as e:
        return JSONResponse(
            status_code=_STATUS_MAP.get(e.code, 429),
            content={"error": {"code": e.code, "message": e.message}},
        )

    return OperationResponse(
        operationId=operation.id,
        status=operation.status,
        warning=None,
        asset=None,
        secondaryAsset=None,
        error=None,
        result=None,
    )
