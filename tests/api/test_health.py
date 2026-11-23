from datetime import datetime

from fastapi import FastAPI
from httpx import AsyncClient

from app.api.v1.endpoints.health import get_database_status


async def test_health_returns_service_metadata(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "FinLedger API"
    assert body["version"] == "0.1.0"
    assert body["environment"] == "test"
    assert datetime.fromisoformat(body["timestamp"]).tzinfo is not None


async def test_readiness_ok_when_database_reachable(app: FastAPI, client: AsyncClient) -> None:
    app.dependency_overrides[get_database_status] = lambda: True

    response = await client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": "ok"}}


async def test_readiness_503_when_database_unreachable(app: FastAPI, client: AsyncClient) -> None:
    app.dependency_overrides[get_database_status] = lambda: False

    response = await client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "checks": {"database": "unavailable"}}
