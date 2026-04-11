from typing import Literal

from pydantic import BaseModel, Field


class ExportRequest(BaseModel):
    format: Literal["wav", "mp3"]
    sample_rate: Literal[22050, 44100, 48000] | None = None
    bitrate_kbps: Literal[128, 192, 256, 320] | None = None


class ExportResponse(BaseModel):
    downloadUrl: str
    format: str
    sampleRate: int
    channels: int
