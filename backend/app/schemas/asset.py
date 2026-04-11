from pydantic import BaseModel

from app.schemas.error import ErrorBody


class UploadResponse(BaseModel):
    assetId: str
    status: str


class AssetResponse(BaseModel):
    assetId: str
    type: str
    status: str
    parentAssetId: str | None
    audioUrl: str | None
    waveformUrl: str | None
    durationSec: float | None
    sampleRate: int | None
    channels: int | None
    error: ErrorBody | None = None
