"""Application settings, validated at startup.

Settings fail closed: a required value that is missing or malformed stops the
process instead of falling back to a default.
"""

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    DEV = "dev"
    TEST = "test"
    PROD = "prod"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True)

    environment: Environment = Environment.DEV
    # No default: the app must never start against an implicit database.
    database_url: PostgresDsn = Field(...)

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

    @property
    def database_url_str(self) -> str:
        return str(self.database_url)


@lru_cache
def get_settings() -> Settings:
    return Settings()
