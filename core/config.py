import os
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    telegram_bot_token: str = "test_bot_token"
    telegram_webhook_secret: Optional[str] = None
    admin_telegram_chat_id: Optional[str] = None

    # Database: Default to sqlite+aiosqlite for zero-config local/test runs
    database_url: str = "sqlite+aiosqlite:///./test_assistant.db"

    # Symmetric encryption key (base64 Fernet key)
    encryption_key: Optional[str] = None

    google_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None

    environment: str = "development"
    port: int = 8000

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
