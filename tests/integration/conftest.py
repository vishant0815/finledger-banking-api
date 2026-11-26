"""Fixtures for tests that run against a real PostgreSQL.

A throwaway `<POSTGRES_DB>_test` database is created once per test session and
migrated with Alembic, so the tests exercise the real schema, constraints and
triggers. Tables are truncated after every test.

If PostgreSQL is unreachable these tests are skipped locally, but fail in CI
(where the `CI` environment variable is set) so they can never be skipped silently.
"""

import asyncio
import os
from collections.abc import AsyncIterator, Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any, NoReturn

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import NullPool, text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings

LEDGER_TABLES = "postings, journal_entries, accounts"


def run_in_thread[T](fn: Callable[..., T], *args: Any) -> T:
    """Run blocking/`asyncio.run`-based code outside pytest-asyncio's event loop."""
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(fn, *args).result()


def alembic_config(database_url: URL) -> Config:
    config = Config()  # no ini file: don't let Alembic reconfigure logging
    config.set_main_option("script_location", "migrations")
    config.attributes["database_url"] = database_url
    return config


async def _recreate_database(admin_url: URL, name: str, *, drop_only: bool = False) -> None:
    conn = await asyncpg.connect(
        user=admin_url.username,
        password=admin_url.password,
        host=admin_url.host,
        port=admin_url.port,
        database=admin_url.database,
        timeout=5,
    )
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        if not drop_only:
            await conn.execute(f'CREATE DATABASE "{name}"')
    finally:
        await conn.close()


def _unavailable(reason: str) -> NoReturn:
    if os.environ.get("CI"):
        pytest.fail(f"PostgreSQL is required in CI: {reason}")
    pytest.skip(f"PostgreSQL not available ({reason}); run `docker compose up -d db`")


@pytest.fixture(scope="session")
def admin_url() -> URL:
    try:
        settings = Settings()
    except ValidationError as exc:
        _unavailable(f"settings incomplete: {exc.errors()[0]['loc']}")
    return settings.database_url


@pytest.fixture(scope="session")
def create_test_database(admin_url: URL) -> Iterator[Callable[[str], URL]]:
    """Factory that creates (and later drops) fresh, empty databases."""
    created: list[str] = []

    def factory(suffix: str) -> URL:
        name = f"{admin_url.database}_{suffix}"
        try:
            run_in_thread(asyncio.run, _recreate_database(admin_url, name))
        except (OSError, asyncpg.PostgresError, TimeoutError) as exc:
            _unavailable(type(exc).__name__)
        created.append(name)
        return admin_url.set(database=name)

    yield factory

    for name in created:
        run_in_thread(asyncio.run, _recreate_database(admin_url, name, drop_only=True))


@pytest.fixture(scope="session")
def migrated_db_url(create_test_database: Callable[[str], URL]) -> URL:
    url = create_test_database("test")
    run_in_thread(command.upgrade, alembic_config(url), "head")
    return url


@pytest.fixture
async def db_engine(migrated_db_url: URL) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(migrated_db_url, poolclass=NullPool)
    yield engine
    # TRUNCATE bypasses the row-level append-only triggers; tests only.
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {LEDGER_TABLES} CASCADE"))
    await engine.dispose()


@pytest.fixture
def session_factory(db_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(db_engine, expire_on_commit=False)


@pytest.fixture
async def session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as db_session:
        yield db_session
