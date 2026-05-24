from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.operation import OperationRequest, OperationResponse
from app.services import operation_service
from app.services.operation_service import OperationError

router = APIRouter(tags=["operations"])


@router.post(
    "/assets/{asset_id}/operations",
    response_model=OperationResponse,
    status_code=202,
)
async def enqueue_operation(
    asset_id: str,
    body: OperationRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        operation = await operation_service.enqueue_operation(
            db,
            user=user,
            input_asset_id=asset_id,
            op_type=body.type,
            parameters=body.parameters.model_dump(),
        )
    except OperationError as e:
        status_map = {
            "ASSET_NOT_FOUND": 404,
            "ASSET_NOT_READY": 409,
            "INVALID_OPERATION": 422,
            "INVALID_PARAMETERS": 422,
        }
        content = {"error": {"code": e.code, "message": e.message}}
        if e.field:
            details: dict = {"field": e.field}
            if e.constraint:
                details["constraint"] = e.constraint
            if e.received is not None:
                details["received"] = e.received
            content["error"]["details"] = details
        return JSONResponse(status_code=status_map.get(e.code, 500), content=content)

    return OperationResponse(
        operationId=operation.id,
        status=operation.status,
        warning=None,
        asset=None,
        secondaryAsset=None,
        error=None,
    )


@router.get(
    "/operations/{operation_id}",
    response_model=OperationResponse,
)
async def get_operation(
    operation_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    op = await operation_service.get_operation_for_user(db, operation_id, user.id)
    if op is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "code": "OPERATION_NOT_FOUND",
                    "message": f"Operation {operation_id} not found",
                }
            },
        )

    response = await operation_service.build_operation_response(db, op)
    payload = response.model_dump()
    for k in ("asset", "secondaryAsset", "error", "warning", "result"):
        if payload.get(k) is None:
            payload.pop(k, None)

    headers = {"Retry-After": "2"} if op.status in ("queued", "running") else {}
    return JSONResponse(content=payload, headers=headers)
