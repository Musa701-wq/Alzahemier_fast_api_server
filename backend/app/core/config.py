from datetime import datetime
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "Yaadasht API"
    VERSION: str = "2.0.0"
    DESCRIPTION: str = "Home cognitive screening, doctor directory, and post-visit care continuity backend."
    DEBUG: bool = True
    HOST: str = "127.0.0.1"
    PORT: int = 8000

    BACKEND_CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "*",
    ]

    SUPABASE_URL: str = ""
    SUPABASE_KEY: str = ""
    JWT_SECRET: str = "yaadasht-local-dev-secret-key-change-in-prod"

    OPENAI_API_KEY: str = ""
    MAX_AUDIO_SIZE_MB: int = 15
    MAX_DOCUMENT_SIZE_MB: int = 20
    DEFAULT_SHARE_EXPIRY_DAYS: int = 14

    SCREENING_DISCLAIMER: str = (
        "Screening aid only, not a medical diagnosis. Please consult a qualified doctor."
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()

