from datetime import datetime

from pydantic import BaseModel

from app.schemas.error import ErrorBody


class UploadResponse(BaseModel):
    assetId: str
    status: str


class AssetResponse(BaseModel):
    assetId: str
    userId: str
    type: str
    status: str
    parentAssetId: str | None
    audioUrl: str | None
    waveformUrl: str | None
    durationSec: float | None
    sampleRate: int | None
    channels: int | None
    filename: str | None
    error: ErrorBody | None = None


class AssetListItem(BaseModel):
    """Row shape for the Dashboard project list. Excludes signed audio URLs to
    keep the list cheap (signed URLs are minted on demand when a user opens
    the project)."""
    assetId: str
    filename: str | None
    status: str
    durationSec: float | None
    sampleRate: int | None
    channels: int | None
    fileSizeBytes: int | None
    createdAt: datetime
    updatedAt: datetime


class AssetListResponse(BaseModel):
    assets: list[AssetListItem]
