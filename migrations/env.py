"""Alembic environment (async, asyncpg).

The database URL comes from application settings (environment variables / .env),
or from `config.attributes["database_url"]` when migrations are run programmatically
(e.g. by the test suite).
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import URL, Connection
from sqlalchemy.ext.asyncio import create_async_engine

import app.models  # noqa: F401  (registers all tables on Base.metadata)
from app.core.config import get_settings
from app.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _database_url() -> URL:
    override = config.attributes.get("database_url")
    if isinstance(override, URL):
        return override
    return get_settings().database_url


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of executing it (`alembic upgrade head --sql`)."""
    context.configure(
        url=_database_url().render_as_string(hide_password=False),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_database_url(), poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
