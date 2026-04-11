from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.schemas.asset import AssetResponse


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


OperationRequest = Annotated[
    TrimOperation
    | DeleteOperation
    | FadeInOperation
    | FadeOutOperation
    | GainOperation
    | NormalizeOperation,
    Field(discriminator="type"),
]


# --- Operation response ---

class OperationResponse(BaseModel):
    operationId: str
    status: str
    warning: str | None = None
    asset: AssetResponse
