"""Async PostgreSQL connectivity (SQLAlchemy 2.0 + asyncpg).

The engine is created in the application lifespan and stored on `app.state`, so each
app instance (including test apps) owns its own connection pool and nothing connects
at import time.
"""

import asyncio
from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings
from app.core.logging import get_logger

logger = get_logger("finledger.db")


def create_db_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout_seconds,
        pool_pre_ping=True,  # transparently replace connections dropped by the server
        echo=settings.db_echo,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    # expire_on_commit=False keeps ORM objects usable after commit in async code,
    # where lazy refreshes would otherwise trigger implicit I/O.
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding one session per request.

    Transaction boundaries are owned by the service layer (added in later phases);
    the context manager guarantees the session is closed and any open transaction
    rolled back when the request finishes.
    """
    session_factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with session_factory() as session:
        yield session


async def ping_database(session: AsyncSession, *, timeout_seconds: float = 2.0) -> bool:
    """Return True if PostgreSQL answers `SELECT 1` within the timeout."""
    try:
        async with asyncio.timeout(timeout_seconds):
            await session.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError, TimeoutError) as exc:
        logger.warning("database.ping_failed", exc_type=type(exc).__name__)
        return False
    return True
