from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=256)
    display_name: str | None = Field(default=None, max_length=120)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class UserResponse(BaseModel):
    userId: str
    email: str | None
    displayName: str | None
    emailVerified: bool


class TokenResponse(BaseModel):
    accessToken: str
    expiresIn: int
    user: UserResponse


class OAuthStartResponse(BaseModel):
    redirectUrl: str


class VerifyEmailRequest(BaseModel):
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")
