from pydantic import BaseModel


class ErrorDetail(BaseModel):
    field: str | None = None
    constraint: str | None = None
    received: float | str | None = None


class ErrorBody(BaseModel):
    code: str
    message: str
    details: ErrorDetail | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody
