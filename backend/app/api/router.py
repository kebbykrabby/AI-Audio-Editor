from fastapi import APIRouter

from app.api.assets import router as assets_router
from app.api.auth import router as auth_router
from app.api.exports import router as exports_router
from app.api.operations import router as operations_router

api_router = APIRouter(prefix="/api")
api_router.include_router(auth_router)
api_router.include_router(assets_router)
api_router.include_router(operations_router)
api_router.include_router(exports_router)
