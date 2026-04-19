import re

from pydantic import BaseModel, EmailStr, Field, field_validator

_PHONE_RE = re.compile(r"^\+[1-9]\d{6,14}$")


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=256)
    display_name: str | None = Field(default=None, max_length=120)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class RequestOtpRequest(BaseModel):
    phone_number: str

    @field_validator("phone_number")
    @classmethod
    def _validate_phone(cls, v: str) -> str:
        if not _PHONE_RE.match(v):
            raise ValueError("phone_number must be E.164, e.g. +14155551234")
        return v


class VerifyOtpRequest(BaseModel):
    phone_number: str
    code: str = Field(min_length=6, max_length=6)

    @field_validator("phone_number")
    @classmethod
    def _validate_phone(cls, v: str) -> str:
        if not _PHONE_RE.match(v):
            raise ValueError("phone_number must be E.164, e.g. +14155551234")
        return v

    @field_validator("code")
    @classmethod
    def _validate_code(cls, v: str) -> str:
        if not v.isdigit():
            raise ValueError("code must be numeric")
        return v


class UserResponse(BaseModel):
    userId: str
    email: str | None
    phoneNumber: str | None
    displayName: str | None
    emailVerified: bool
    phoneVerified: bool


class TokenResponse(BaseModel):
    accessToken: str
    expiresIn: int
    user: UserResponse


class OAuthStartResponse(BaseModel):
    redirectUrl: str
