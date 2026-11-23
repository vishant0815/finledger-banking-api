from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.exceptions import ConflictError
from app.core.middleware import REQUEST_ID_HEADER


@pytest.fixture
def app_with_test_routes(app: FastAPI) -> FastAPI:
    @app.get("/_test/conflict")
    async def raise_conflict() -> None:
        raise ConflictError("Account is frozen.", details={"account_id": "acc_123"})

    @app.get("/_test/boom")
    async def raise_unexpected() -> None:
        raise RuntimeError("database password is hunter2")  # must never reach the client

    @app.get("/_test/items/{item_id}")
    async def typed_param(item_id: int) -> dict[str, int]:
        return {"item_id": item_id}

    return app


@pytest.fixture
async def test_client(app_with_test_routes: FastAPI) -> AsyncIterator[AsyncClient]:
    # raise_app_exceptions=False lets us assert on the 500 response instead of
    # having the test client re-raise the original exception.
    transport = ASGITransport(app=app_with_test_routes, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_generates_request_id_when_missing(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")

    request_id = response.headers[REQUEST_ID_HEADER]
    assert len(request_id) == 32
    int(request_id, 16)  # valid hex


async def test_propagates_valid_incoming_request_id(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health", headers={REQUEST_ID_HEADER: "client-abc.123"})

    assert response.headers[REQUEST_ID_HEADER] == "client-abc.123"


@pytest.mark.parametrize("bad_id", ["has spaces", "a" * 129, "semi;colon", "<script>"])
async def test_replaces_unsafe_incoming_request_id(client: AsyncClient, bad_id: str) -> None:
    response = await client.get("/api/v1/health", headers={REQUEST_ID_HEADER: bad_id})

    assert response.headers[REQUEST_ID_HEADER] != bad_id


async def test_unknown_route_uses_error_envelope(client: AsyncClient) -> None:
    response = await client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "not_found"
    assert error["request_id"] == response.headers[REQUEST_ID_HEADER]


async def test_method_not_allowed_uses_error_envelope(client: AsyncClient) -> None:
    response = await client.post("/api/v1/health")

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"


async def test_app_error_is_mapped_to_its_status_and_code(test_client: AsyncClient) -> None:
    response = await test_client.get("/_test/conflict")

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "conflict"
    assert error["message"] == "Account is frozen."
    assert error["details"] == {"account_id": "acc_123"}


async def test_validation_error_hides_input_values(test_client: AsyncClient) -> None:
    response = await test_client.get("/_test/items/not-a-number")

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["details"][0]["loc"] == ["path", "item_id"]
    assert "not-a-number" not in response.text


async def test_unhandled_exception_returns_generic_500(test_client: AsyncClient) -> None:
    response = await test_client.get("/_test/boom")

    assert response.status_code == 500
    error = response.json()["error"]
    assert error["code"] == "internal_error"
    assert error["message"] == "An unexpected error occurred."
    assert "hunter2" not in response.text
    assert response.headers[REQUEST_ID_HEADER] == error["request_id"]
