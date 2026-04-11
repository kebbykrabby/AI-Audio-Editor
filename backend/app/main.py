import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, update

from app.api.router import api_router
from app.config import settings
from app.database import Base, async_session, engine
from app.models.asset import Asset

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)

MAX_BODY_BYTES = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024

STALE_PROCESSING_MINUTES = 5


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables on startup (dev only; use Alembic in production)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Recover assets stuck in "processing" from a prior crash
    cutoff = datetime.utcnow() - timedelta(minutes=STALE_PROCESSING_MINUTES)
    async with async_session() as db:
        result = await db.execute(
            update(Asset)
            .where(Asset.status == "processing", Asset.created_at < cutoff)
            .values(
                status="failed",
                error_code="SERVER_RESTART",
                error_message="Processing was interrupted by a server restart",
            )
        )
        await db.commit()
        if result.rowcount:
            logger.info("Recovered %d stale processing asset(s)", result.rowcount)

    yield


app = FastAPI(title="AI Audio Editor", version="0.1.0", lifespan=lifespan)


# Reject oversized request bodies early via Content-Length header
@app.middleware("http")
async def limit_upload_size(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_BODY_BYTES:
        return JSONResponse(
            status_code=413,
            content={"error": {"code": "INVALID_FILE", "message": f"Request body exceeds {settings.MAX_UPLOAD_SIZE_MB}MB limit"}},
        )
    return await call_next(request)


# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes
app.include_router(api_router)

# Static file serving for storage (waveforms, exports)
storage_path = Path(settings.STORAGE_ROOT)
storage_path.mkdir(parents=True, exist_ok=True)
app.mount("/files", StaticFiles(directory=str(storage_path)), name="files")
