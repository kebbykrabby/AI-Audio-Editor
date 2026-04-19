from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Core
    DATABASE_URL: str = "postgresql+asyncpg://audio:audio@localhost:5432/audio_editor"
    CORS_ORIGINS: list[str] = ["http://localhost:5173"]
    MAX_UPLOAD_SIZE_MB: int = 100
    FRONTEND_BASE_URL: str = "http://localhost:5173"

    # Queue / workers
    REDIS_URL: str = "redis://localhost:6379/0"
    # Stale-running sweep runs on API startup; threshold must exceed the per-job
    # ceiling plus a safety margin so in-flight jobs that out-survive an API
    # restart aren't mistakenly marked failed.
    WORKER_STALE_RUNNING_MIN: int = 40
    WORKER_TIME_LIMIT_SEC: int = 1800  # per-job hard ceiling inside the actor
    WORKER_AGE_LIMIT_SEC: int = 3600   # drop messages older than this

    # Storage
    STORAGE_BACKEND: str = "local"  # "local" | "s3"
    STORAGE_ROOT: str = "./storage"  # local backend only
    STORAGE_LOCAL_URL_PREFIX: str = "/files"
    # Signed-URL TTL for S3 backend (seconds). Short by design to limit the
    # blast radius of a leaked URL. Frontend pre-emptively refetches at 8 min
    # while viewing an asset, so 10-min TTL gives a 2-min safety margin.
    SIGNED_URL_TTL_SEC: int = 600

    # S3-compatible (AWS S3 / R2 / MinIO)
    S3_ENDPOINT_URL: str | None = None  # None = AWS; set for R2/MinIO
    S3_BUCKET: str | None = None
    S3_REGION: str = "us-east-1"
    S3_ACCESS_KEY_ID: str | None = None
    S3_SECRET_ACCESS_KEY: str | None = None
    S3_USE_PATH_STYLE: bool = False  # True for MinIO
    S3_PUBLIC_URL_BASE: str | None = None  # optional CDN/base URL override

    # JWT / auth
    JWT_SECRET: str = "dev-only-insecure-secret-change-in-prod"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TTL_MIN: int = 15
    REFRESH_TTL_DAYS: int = 30

    # Cookie
    COOKIE_SECURE: bool = False  # True in prod (HTTPS only)
    COOKIE_DOMAIN: str | None = None
    COOKIE_SAMESITE: str = "lax"
    REFRESH_COOKIE_NAME: str = "refresh"
    CSRF_COOKIE_NAME: str = "csrf"
    CSRF_HEADER_NAME: str = "X-CSRF-Token"

    # OTP
    OTP_TTL_MIN: int = 10
    OTP_MAX_ATTEMPTS: int = 5
    OTP_RATE_PHONE_PER_MIN: int = 1
    OTP_RATE_PHONE_PER_HOUR: int = 5
    OTP_RATE_IP_PER_HOUR: int = 10

    # SMS provider — "console" for local dev, "twilio" for prod
    SMS_PROVIDER: str = "console"
    TWILIO_ACCOUNT_SID: str | None = None
    TWILIO_AUTH_TOKEN: str | None = None
    TWILIO_FROM_NUMBER: str | None = None

    # Google OAuth
    GOOGLE_CLIENT_ID: str | None = None
    GOOGLE_CLIENT_SECRET: str | None = None
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/api/auth/oauth/google/callback"

    # Apple OAuth
    APPLE_CLIENT_ID: str | None = None  # Services ID, e.g. "com.yourapp.web"
    APPLE_TEAM_ID: str | None = None
    APPLE_KEY_ID: str | None = None
    APPLE_PRIVATE_KEY_PATH: str | None = None  # path to AuthKey_XXX.p8
    APPLE_REDIRECT_URI: str = "http://localhost:8000/api/auth/oauth/apple/callback"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
