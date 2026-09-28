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
