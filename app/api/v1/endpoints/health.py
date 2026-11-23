from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.api.deps import DbSessionDep, SettingsDep
from app.db.session import ping_database
from app.schemas.health import CheckStatus, HealthResponse, ReadinessResponse

router = APIRouter(prefix="/health", tags=["health"])


async def get_database_status(session: DbSessionDep) -> bool:
    return await ping_database(session)


@router.get(
    "",
    response_model=HealthResponse,
    summary="Liveness check",
    description="Confirms the API process is running. Does not touch external dependencies.",
)
async def health(settings: SettingsDep) -> HealthResponse:
    return HealthResponse(
        service=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
        timestamp=datetime.now(UTC),
    )


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Readiness check",
    description="Confirms the API can serve traffic, including PostgreSQL connectivity.",
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessResponse}},
)
async def readiness(
    response: Response,
    database_ok: Annotated[bool, Depends(get_database_status)],
) -> ReadinessResponse:
    if not database_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    database_status: CheckStatus = "ok" if database_ok else "unavailable"
    return ReadinessResponse(status=database_status, checks={"database": database_status})
