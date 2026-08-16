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

    # AI & Multimodal Models
    google_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None
    gemini_model: str = "gemini-3.1-flash-lite"
    gemini_judge_model: str = "gemini-3.1-pro"
    deepseek_api_key: Optional[str] = None
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-v4-flash"
    llm_provider: str = "deepseek"
    openai_api_key: Optional[str] = None
    openrouter_api_key: Optional[str] = None
    openrouter_model: Optional[str] = None

    # Capability Plugin & External Service API Keys
    tavily_api_key: Optional[str] = None
    google_client_id: Optional[str] = None
    google_client_secret: Optional[str] = None
    google_maps_api_key: Optional[str] = None
    lta_account_key: Optional[str] = None
    microsoft_client_id: Optional[str] = None
    microsoft_client_secret: Optional[str] = None
    outlook_email: Optional[str] = None
    outlook_app_password: Optional[str] = None
    webapp_url: Optional[str] = None

    environment: str = "development"
    port: int = 8000

    @property
    def active_gemini_api_key(self) -> Optional[str]:
        """Returns either GEMINI_API_KEY or GOOGLE_API_KEY if set."""
        return self.gemini_api_key or self.google_api_key

    @property
    def resolved_database_url(self) -> str:
        """Returns an absolute SQLite file URI when a relative path is configured."""
        url = self.database_url
        if url.startswith("sqlite+aiosqlite:///./"):
            rel_path = url.replace("sqlite+aiosqlite:///./", "")
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            abs_db_path = os.path.join(base_dir, rel_path)
            return f"sqlite+aiosqlite:///{abs_db_path}"
        return url

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
