"""Application settings, validated at startup.

Settings fail closed: a required value that is missing or malformed stops the
process instead of falling back to a default.
"""

from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Self

from pydantic import Field, PostgresDsn, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Environment(StrEnum):
    DEV = "dev"
    TEST = "test"
    PROD = "prod"


class LlmProvider(StrEnum):
    GEMINI = "gemini"
    OPENROUTER = "openrouter"
    DEEPSEEK = "deepseek"
    OPENAI = "openai"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True)

    environment: Environment = Environment.DEV
    # No default: the app must never start against an implicit database.
    database_url: PostgresDsn = Field(...)

    # --- Telegram. Unset token = Telegram channel disabled. ---
    telegram_bot_token: SecretStr | None = None
    telegram_webhook_secret: SecretStr | None = None
    # The owner's Telegram user id (same as their private chat id).
    admin_telegram_chat_id: int | None = None
    # Further Telegram user ids allowed to use the bot, comma separated.
    telegram_allowed_user_ids: Annotated[tuple[int, ...], NoDecode] = ()
    default_home_currency: str = "SGD"
    default_timezone: str = "Asia/Singapore"

    # --- Web. The origin browsers use; CSRF checks compare against it. ---
    web_origin: str | None = None
    railway_public_domain: str | None = None

    # --- Background jobs (reminders, budget alerts). Unset: on in prod only, so
    # tests and local runs don't send messages unless asked to. ---
    jobs_enabled: bool | None = None

    # --- Receipt archive: a private S3-compatible bucket (Railway bucket variables).
    # All or nothing; unset = receipts aren't kept. ---
    storage_bucket: str | None = None
    storage_endpoint: str | None = None
    storage_region: str = "auto"
    storage_access_key_id: SecretStr | None = None
    storage_secret_access_key: SecretStr | None = None
    storage_path_style: bool = False

    # --- LLM. Names match the pre-rebuild deployment's variables. ---
    llm_provider: LlmProvider = LlmProvider.GEMINI
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-3.7-flash"
    llm_fallback_model: str | None = None
    openrouter_api_key: SecretStr | None = None
    openrouter_model: str | None = None
    deepseek_api_key: SecretStr | None = None
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-v4-flash"
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-4o-mini"
    llm_request_timeout_seconds: float = Field(default=30.0, gt=0)
    llm_max_retries: int = Field(default=2, ge=0)

    @field_validator("database_url", mode="before")
    @classmethod
    def _use_asyncpg_driver(cls, value: object) -> object:
        """Accept the plain URLs Railway and docker-compose hand out."""
        if isinstance(value, str):
            for prefix in ("postgres://", "postgresql://"):
                if value.startswith(prefix):
                    return "postgresql+asyncpg://" + value.removeprefix(prefix)
        return value

    @field_validator("database_url")
    @classmethod
    def _require_asyncpg(cls, value: PostgresDsn) -> PostgresDsn:
        if value.scheme != "postgresql+asyncpg":
            raise ValueError("database_url must use the postgresql+asyncpg driver")
        return value

    @field_validator("llm_provider", mode="before")
    @classmethod
    def _lowercase_provider(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("telegram_allowed_user_ids", mode="before")
    @classmethod
    def _split_ids(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(int(part) for part in value.replace(" ", "").split(",") if part)
        return value

    @field_validator(
        "telegram_bot_token",
        "telegram_webhook_secret",
        "gemini_api_key",
        "openrouter_api_key",
        "deepseek_api_key",
        "openai_api_key",
        "storage_access_key_id",
        "storage_secret_access_key",
        "storage_bucket",
        "storage_endpoint",
        mode="before",
    )
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @model_validator(mode="after")
    def _telegram_needs_its_guards(self) -> Self:
        if self.telegram_bot_token is not None:
            if self.telegram_webhook_secret is None:
                raise ValueError("TELEGRAM_WEBHOOK_SECRET is required when Telegram is enabled")
            if self.admin_telegram_chat_id is None:
                raise ValueError("ADMIN_TELEGRAM_CHAT_ID is required when Telegram is enabled")
        return self

    @model_validator(mode="after")
    def _storage_all_or_nothing(self) -> Self:
        parts = {
            "STORAGE_BUCKET": self.storage_bucket,
            "STORAGE_ENDPOINT": self.storage_endpoint,
            "STORAGE_ACCESS_KEY_ID": self.storage_access_key_id,
            "STORAGE_SECRET_ACCESS_KEY": self.storage_secret_access_key,
        }
        missing = [name for name, value in parts.items() if value is None]
        if missing and len(missing) < len(parts):
            raise ValueError(f"receipt storage is half configured; missing {', '.join(missing)}")
        return self

    @property
    def storage_enabled(self) -> bool:
        return self.storage_bucket is not None

    @property
    def database_url_str(self) -> str:
        return str(self.database_url)

    @property
    def public_origin(self) -> str | None:
        if self.web_origin:
            return self.web_origin.rstrip("/")
        if self.railway_public_domain:
            return f"https://{self.railway_public_domain.strip()}"
        return None

    @property
    def web_enabled(self) -> bool:
        """The web app needs Telegram (login) and a known origin (CSRF)."""
        return self.telegram_enabled and self.public_origin is not None

    @property
    def run_jobs(self) -> bool:
        if self.jobs_enabled is not None:
            return self.jobs_enabled
        return self.environment is Environment.PROD

    @property
    def telegram_enabled(self) -> bool:
        return self.telegram_bot_token is not None

    @property
    def allowed_telegram_user_ids(self) -> frozenset[int]:
        owner = {self.admin_telegram_chat_id} if self.admin_telegram_chat_id is not None else set()
        return frozenset(owner | set(self.telegram_allowed_user_ids))


@lru_cache
def get_settings() -> Settings:
    return Settings()
