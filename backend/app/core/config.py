from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "Yaadasht API"
    VERSION: str = "2.1.0"
    DESCRIPTION: str = "Personalized & adaptive cognitive screening, doctor directory, and post-visit care continuity backend."
    DEBUG: bool = True
    HOST: str = "127.0.0.1"
    PORT: int = 8000

    BACKEND_CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "*",
    ]

    # MongoDB Configuration
    MONGODB_URI: str = "mongodb://127.0.0.1:27017"
    MONGODB_DB_NAME: str = "yaadasht_db"

    SUPABASE_URL: str = ""
    SUPABASE_KEY: str = ""
    JWT_SECRET: str = "yaadasht-local-dev-secret-key-change-in-prod"

    # OpenRouter AI Configuration
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENROUTER_MODEL: str = "openrouter/auto"
    SITE_URL: str = "http://127.0.0.1:8000"
    SITE_NAME: str = "Yaadasht Cognitive Screening"

    MAX_AUDIO_SIZE_MB: int = 15
    MAX_DOCUMENT_SIZE_MB: int = 20
    DEFAULT_SHARE_EXPIRY_DAYS: int = 14

    SCREENING_DISCLAIMER: str = (
        "Screening aid only, not a medical diagnosis. Please consult a qualified doctor."
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()
