from typing import Any

import pytest
from pydantic import ValidationError

from nexus.settings import Environment, Settings


def test_missing_database_url_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError, match="database_url"):
        Settings(_env_file=None)


@pytest.mark.parametrize(
    "raw",
    [
        "postgres://u:p@db:5432/nexus",
        "postgresql://u:p@db:5432/nexus",
        "postgresql+asyncpg://u:p@db:5432/nexus",
    ],
)
def test_database_url_is_normalised_to_asyncpg(raw: str) -> None:
    settings = Settings(_env_file=None, database_url=raw)
    assert settings.database_url_str == "postgresql+asyncpg://u:p@db:5432/nexus"


def test_other_drivers_are_rejected() -> None:
    with pytest.raises(ValidationError, match="asyncpg"):
        Settings(_env_file=None, database_url="postgresql+psycopg://u:p@db/nexus")


def test_unknown_environment_is_rejected() -> None:
    with pytest.raises(ValidationError, match="environment"):
        Settings(_env_file=None, database_url="postgresql://u:p@db/nexus", environment="staging")


def test_environment_defaults_to_dev() -> None:
    settings = Settings(_env_file=None, database_url="postgresql://u:p@db/nexus")
    assert settings.environment is Environment.DEV


def _telegram(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "database_url": "postgresql://u:p@db/nexus",
        "telegram_bot_token": "123:abc",
        "telegram_webhook_secret": "s3cret",
        "admin_telegram_chat_id": 42,
    }
    values.update(overrides)
    return values


def test_telegram_requires_webhook_secret_and_owner() -> None:
    with pytest.raises(ValidationError, match="TELEGRAM_WEBHOOK_SECRET"):
        Settings(_env_file=None, **_telegram(telegram_webhook_secret=" "))
    with pytest.raises(ValidationError, match="ADMIN_TELEGRAM_CHAT_ID"):
        Settings(_env_file=None, **_telegram(admin_telegram_chat_id=None))


def test_allowed_users_include_the_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "7, 8")
    settings = Settings(_env_file=None, **_telegram())
    assert settings.telegram_enabled
    assert settings.allowed_telegram_user_ids == {7, 8, 42}


def test_telegram_is_off_without_a_token() -> None:
    settings = Settings(_env_file=None, database_url="postgresql://u:p@db/nexus")
    assert not settings.telegram_enabled
    assert settings.allowed_telegram_user_ids == frozenset()


def test_llm_provider_is_case_insensitive() -> None:
    settings = Settings(_env_file=None, database_url="postgresql://u:p@db/n", llm_provider="Gemini")
    assert settings.llm_provider.value == "gemini"
