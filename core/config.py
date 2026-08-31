import os
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    telegram_bot_token: str = "test_bot_token"
    telegram_webhook_secret: Optional[str] = None
    admin_telegram_chat_id: Optional[str] = None
    audit_telegram_alerts: bool = False  # Keep audit findings in DB/GitHub unless explicitly enabled

    # Database: Default to sqlite+aiosqlite for zero-config local/test runs
    database_url: str = "sqlite+aiosqlite:///./test_assistant.db"

    # Symmetric encryption key (base64 Fernet key)
    encryption_key: Optional[str] = None

    # AI & Multimodal Models
    google_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None
    gemini_model: str = "gemini-3.7-flash"
    gemini_judge_model: str = "gemini-3.1-pro-preview"
    deepseek_api_key: Optional[str] = None
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-v4-flash"
    llm_provider: str = "gemini"
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
    microsoft_tenant: str = "consumers"  # Personal Microsoft accounts use /consumers, not /common
    outlook_email: Optional[str] = None
    outlook_app_password: Optional[str] = None
    webapp_url: Optional[str] = None

    environment: str = "development"
    port: int = 8000

    # Filesystem storage root (relative to project root) for generated artifacts
    # such as AI board cover art. On Railway, set DATA_DIR="/data" to use the
    # persistent volume.
    data_dir: str = "data"

    @property
    def active_gemini_api_key(self) -> Optional[str]:
        """Returns either GEMINI_API_KEY or GOOGLE_API_KEY if set."""
        return self.gemini_api_key or self.google_api_key

    @property
    def has_llm_key(self) -> bool:
        """Returns True if an active LLM provider (Gemini or DeepSeek) has a valid key configured."""
        if self.llm_provider == "gemini":
            return bool(self.active_gemini_api_key and self.active_gemini_api_key != "test_google_key")
        return bool(
            (self.deepseek_api_key and self.deepseek_api_key != "test_deepseek_key")
            or (self.active_gemini_api_key and self.active_gemini_api_key != "test_google_key")
        )

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

    @property
    def resolved_data_dir(self) -> str:
        """Returns an absolute filesystem path for the data/artifacts directory."""
        if os.path.isabs(self.data_dir):
            return self.data_dir
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base_dir, self.data_dir)

    # Capability Access Control — skills a non-admin user must never reach.
    admin_only_capabilities: set[str] = {"code-exec"}
    # Outer bound on a whole graph turn (ingress + web chat). The agent loop
    # inside is deliberately unbounded; this exists only so a wedged turn --
    # e.g. hung checkpoint I/O -- degrades into an honest error reply and a
    # checkpointer reset instead of a silently dead chat.
    graph_turn_timeout_seconds: float = 600.0

    def is_admin(self, user_id: Optional[object]) -> bool:
        """
        Check if user_id matches admin_telegram_chat_id.
        If no admin_telegram_chat_id is set, default to True for local testing.
        """
        if not self.admin_telegram_chat_id:
            return True
        if not user_id:
            return False
        return str(user_id).strip() == str(self.admin_telegram_chat_id).strip()

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
