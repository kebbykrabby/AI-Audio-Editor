from typing import Literal

from pydantic import BaseModel

from app.schemas.error import ErrorBody


class ExportRequest(BaseModel):
    format: Literal["wav", "mp3"]
    sample_rate: Literal[22050, 44100, 48000] | None = None
    bitrate_kbps: Literal[128, 192, 256, 320] | None = None


class ExportResponse(BaseModel):
    exportId: str
    status: str  # "queued" | "running" | "completed" | "failed"
    format: str
    sampleRate: int | None = None
    bitrateKbps: int | None = None
    channels: int | None = None
    downloadUrl: str | None = None
    error: ErrorBody | None = None
