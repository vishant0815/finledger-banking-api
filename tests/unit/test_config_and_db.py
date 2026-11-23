from typing import Any, cast

import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.session import ping_database
from app.main import create_app


class _StubSession:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    async def execute(self, *_: Any, **__: Any) -> None:
        if self.error:
            raise self.error


def test_password_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)

    with pytest.raises(ValidationError, match="postgres_password"):
        Settings(_env_file=None)


def test_database_url_uses_asyncpg_and_masks_password(settings: Settings) -> None:
    url = settings.database_url

    assert url.drivername == "postgresql+asyncpg"
    assert "test-password" not in str(url)
    assert url.password == "test-password"


def test_api_docs_disabled_in_production(settings: Settings) -> None:
    prod = settings.model_copy(update={"environment": "production"})

    app = create_app(prod)

    assert app.openapi_url is None
    assert app.docs_url is None


def test_api_docs_enabled_outside_production(settings: Settings) -> None:
    app = create_app(settings)

    assert app.docs_url == "/docs"


async def test_ping_database_true_when_query_succeeds() -> None:
    assert await ping_database(cast(AsyncSession, _StubSession())) is True


@pytest.mark.parametrize(
    "error",
    [
        OperationalError("SELECT 1", {}, Exception("connection refused")),
        ConnectionRefusedError(),
        TimeoutError(),
    ],
)
async def test_ping_database_false_when_query_fails(error: Exception) -> None:
    assert await ping_database(cast(AsyncSession, _StubSession(error))) is False


def test_settings_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_PASSWORD", "from-env")
    monkeypatch.setenv("POSTGRES_HOST", "db")

    settings = Settings(_env_file=None)

    assert settings.postgres_password == SecretStr("from-env")
    assert settings.database_url.host == "db"
