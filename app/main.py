"""Application factory.

Run locally with:
    uv run uvicorn app.main:create_app --factory --reload
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestContextMiddleware
from app.db.session import create_db_engine, create_session_factory

logger = get_logger("finledger")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    engine = create_db_engine(settings)
    app.state.db_engine = engine
    app.state.session_factory = create_session_factory(engine)
    logger.info(
        "application.startup",
        environment=settings.environment,
        version=settings.app_version,
        database=settings.database_url.render_as_string(hide_password=True),
    )
    try:
        yield
    finally:
        await engine.dispose()
        logger.info("application.shutdown")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json_logs=settings.log_json)

    # Interactive API docs are disabled in production.
    docs_enabled = not settings.is_production
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Double-entry banking ledger and money transfer API.",
        debug=settings.debug,
        lifespan=lifespan,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )
    app.state.settings = settings

    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.api_v1_prefix)
    return app
