from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.schemas.asset import AssetResponse
from app.schemas.error import ErrorBody


# --- Parameter models per operation type ---

class TrimParams(BaseModel):
    start_sec: float = Field(ge=0)
    end_sec: float = Field(ge=0)


class DeleteParams(BaseModel):
    start_sec: float = Field(ge=0)
    end_sec: float = Field(ge=0)


class FadeInParams(BaseModel):
    duration_sec: float = Field(gt=0)
    curve: Literal["linear", "exponential"] = "linear"


class FadeOutParams(BaseModel):
    duration_sec: float = Field(gt=0)
    curve: Literal["linear", "exponential"] = "linear"


class GainParams(BaseModel):
    gain_db: float = Field(ge=-60, le=24)


class NormalizeParams(BaseModel):
    target_db: float = Field(ge=-60, le=0)


class ReverseParams(BaseModel):
    pass


class RemoveSilenceParams(BaseModel):
    threshold_db: float = Field(ge=-80, le=0, default=-40)
    min_silence_sec: float = Field(gt=0, le=10, default=0.5)


class ExtractChannelParams(BaseModel):
    channel: Literal["left", "right"]


class SwapChannelsParams(BaseModel):
    pass


class MonoMixdownParams(BaseModel):
    pass


class SpeedParams(BaseModel):
    factor: float = Field(ge=0.25, le=4.0)


class SplitChannelsParams(BaseModel):
    pass


class MergeChannelsParams(BaseModel):
    right_asset_id: str


class ReverseRangeParams(BaseModel):
    """Reverse only [start_sec, end_sec], keep the rest unchanged."""
    start_sec: float = Field(ge=0)
    end_sec: float = Field(gt=0)


class GainRangeParams(BaseModel):
    """Apply gain_db only in [start_sec, end_sec]."""
    start_sec: float = Field(ge=0)
    end_sec: float = Field(gt=0)
    gain_db: float = Field(ge=-60, le=24)


class RemoveSegmentsInterval(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)


class RemoveSegmentsParams(BaseModel):
    intervals: list[RemoveSegmentsInterval] = Field(min_length=1, max_length=500)
    crossfade_ms: float = Field(ge=5, le=100, default=20.0)


class CensorSegmentsInterval(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)


class CensorSegmentsParams(BaseModel):
    intervals: list[CensorSegmentsInterval] = Field(min_length=1, max_length=500)
    # beep: 1 kHz sine over each region (duration-preserving).
    # mute: silence each region (duration-preserving).
    # cut: delete each region with crossfade (duration-SHORTENING; delegates
    #      internally to the same DSP as remove_segments).
    # reverse_pitch: reverse + pitch-shift each region (duration-preserving).
    mode: Literal["beep", "mute", "cut", "reverse_pitch"] = "beep"
    # Beep tone frequency in Hz. Default 1 kHz mirrors broadcast convention.
    # Ignored when mode != "beep".
    beep_hz: int = Field(ge=200, le=8000, default=1000)
    # Crossfade width for mode="cut". Ignored otherwise. Matches remove_segments default.
    crossfade_ms: float = Field(ge=5, le=100, default=20.0)


# --- Operation request models (discriminated union) ---

class TrimOperation(BaseModel):
    type: Literal["trim"]
    parameters: TrimParams


class DeleteOperation(BaseModel):
    type: Literal["delete"]
    parameters: DeleteParams


class FadeInOperation(BaseModel):
    type: Literal["fade_in"]
    parameters: FadeInParams


class FadeOutOperation(BaseModel):
    type: Literal["fade_out"]
    parameters: FadeOutParams


class GainOperation(BaseModel):
    type: Literal["gain"]
    parameters: GainParams


class NormalizeOperation(BaseModel):
    type: Literal["normalize"]
    parameters: NormalizeParams


class ReverseOperation(BaseModel):
    type: Literal["reverse"]
    parameters: ReverseParams


class RemoveSilenceOperation(BaseModel):
    type: Literal["remove_silence"]
    parameters: RemoveSilenceParams


class ExtractChannelOperation(BaseModel):
    type: Literal["extract_channel"]
    parameters: ExtractChannelParams


class SwapChannelsOperation(BaseModel):
    type: Literal["swap_channels"]
    parameters: SwapChannelsParams


class MonoMixdownOperation(BaseModel):
    type: Literal["mono_mixdown"]
    parameters: MonoMixdownParams


class SpeedOperation(BaseModel):
    type: Literal["speed"]
    parameters: SpeedParams


class SplitChannelsOperation(BaseModel):
    type: Literal["split_channels"]
    parameters: SplitChannelsParams


class MergeChannelsOperation(BaseModel):
    type: Literal["merge_channels"]
    parameters: MergeChannelsParams


class RemoveSegmentsOperation(BaseModel):
    type: Literal["remove_segments"]
    parameters: RemoveSegmentsParams


class CensorSegmentsOperation(BaseModel):
    type: Literal["censor_segments"]
    parameters: CensorSegmentsParams


class ReverseRangeOperation(BaseModel):
    type: Literal["reverse_range"]
    parameters: ReverseRangeParams


class GainRangeOperation(BaseModel):
    type: Literal["gain_range"]
    parameters: GainRangeParams


OperationRequest = Annotated[
    TrimOperation
    | DeleteOperation
    | FadeInOperation
    | FadeOutOperation
    | GainOperation
    | NormalizeOperation
    | ReverseOperation
    | RemoveSilenceOperation
    | ExtractChannelOperation
    | SwapChannelsOperation
    | MonoMixdownOperation
    | SpeedOperation
    | SplitChannelsOperation
    | MergeChannelsOperation
    | RemoveSegmentsOperation
    | CensorSegmentsOperation
    | ReverseRangeOperation
    | GainRangeOperation,
    Field(discriminator="type"),
]


# --- Operation response ---

class OperationResponse(BaseModel):
    operationId: str
    status: str  # "queued" | "running" | "completed" | "failed" | "cancelled"
    warning: str | None = None
    asset: AssetResponse | None = None
    secondaryAsset: AssetResponse | None = None
    error: ErrorBody | None = None
    # For AI ops (ai_detect_fillers) that return structured data rather than an
    # asset. None for deterministic ops. Shape is op-type-specific; the client
    # uses the op's `type` to interpret.
    result: dict | None = None
