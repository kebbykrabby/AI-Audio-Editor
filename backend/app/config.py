from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite+aiosqlite:///./audio_editor.db"
    STORAGE_ROOT: str = "./storage"
    CORS_ORIGINS: list[str] = ["http://localhost:5173"]
    MAX_UPLOAD_SIZE_MB: int = 100

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
