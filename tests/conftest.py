"""Shared test fixtures.

The suite needs no running PostgreSQL, Kafka or Redis: database checks are
replaced with dependency overrides where needed.
"""

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,  # ignore any local .env
        environment="test",
        log_level="WARNING",
        postgres_password=SecretStr("test-password"),
    )


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=transport, base_url="http://test") as http_client,
    ):
        yield http_client
