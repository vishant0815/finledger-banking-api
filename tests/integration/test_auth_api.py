"""End-to-end auth tests: HTTP -> FastAPI -> services -> real PostgreSQL."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.security import create_access_token
from app.models.user import User, UserRole

pytestmark = pytest.mark.integration

PASSWORD = "correct-horse-battery-staple"


async def register(
    client: AsyncClient, email: str = "alice@example.com", password: str = PASSWORD
) -> dict[str, object]:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": "Alice Smith"},
    )
    assert response.status_code == 201, response.text
    body: dict[str, object] = response.json()
    return body


async def login(
    client: AsyncClient, email: str = "alice@example.com", password: str = PASSWORD
) -> str:
    response = await client.post(
        "/api/v1/auth/login", data={"username": email, "password": password}
    )
    assert response.status_code == 200, response.text
    token: str = response.json()["access_token"]
    return token


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def set_user(
    session_factory: async_sessionmaker[AsyncSession], email: str, **values: object
) -> None:
    async with session_factory() as session:
        await session.execute(update(User).where(User.email == email).values(**values))
        await session.commit()


# ---------------------------------------------------------------- registration


async def test_register_creates_customer_without_exposing_hash(
    api_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    body = await register(api_client, email="Alice@Example.com")

    assert body["email"] == "alice@example.com"
    assert body["role"] == "customer"
    assert body["is_active"] is True
    assert "password" not in str(body)
    assert "hash" not in str(body)

    async with session_factory() as session:
        user = await session.scalar(select(User).where(User.email == "alice@example.com"))
        assert user is not None
        assert user.password_hash.startswith("$argon2id$")


async def test_duplicate_email_is_rejected_case_insensitively(api_client: AsyncClient) -> None:
    await register(api_client, email="alice@example.com")

    response = await api_client.post(
        "/api/v1/auth/register",
        json={"email": "ALICE@example.com", "password": PASSWORD, "full_name": "Imposter"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "email_already_registered"


async def test_concurrent_duplicate_registrations_create_exactly_one_user(
    api_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    payload = {"email": "race@example.com", "password": PASSWORD, "full_name": "Racer"}

    responses = await asyncio.gather(
        *(api_client.post("/api/v1/auth/register", json=payload) for _ in range(5))
    )

    assert sorted(r.status_code for r in responses) == [201, 409, 409, 409, 409]
    async with session_factory() as session:
        users = (await session.scalars(select(User).where(User.email == "race@example.com"))).all()
        assert len(users) == 1


async def test_weak_password_is_rejected_without_echoing_it(api_client: AsyncClient) -> None:
    response = await api_client.post(
        "/api/v1/auth/register",
        json={"email": "bob@example.com", "password": "hunter2", "full_name": "Bob"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["loc"] == ["body", "password"]
    assert "hunter2" not in response.text


# ----------------------------------------------------------------------- login


async def test_login_returns_bearer_token(api_client: AsyncClient) -> None:
    await register(api_client)

    response = await api_client.post(
        "/api/v1/auth/login", data={"username": "ALICE@example.com", "password": PASSWORD}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 15 * 60
    assert body["access_token"].count(".") == 2


@pytest.mark.parametrize(
    ("email", "password"),
    [("alice@example.com", "wrong-password-123"), ("nobody@example.com", PASSWORD)],
    ids=["wrong-password", "unknown-email"],
)
async def test_failed_login_gives_identical_generic_error(
    api_client: AsyncClient, email: str, password: str
) -> None:
    await register(api_client)

    response = await api_client.post(
        "/api/v1/auth/login", data={"username": email, "password": password}
    )

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    error = response.json()["error"]
    assert (error["code"], error["message"]) == (
        "invalid_credentials",
        "Incorrect email or password.",
    )


async def test_inactive_user_cannot_log_in(
    api_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await register(api_client)
    await set_user(session_factory, "alice@example.com", is_active=False)

    response = await api_client.post(
        "/api/v1/auth/login", data={"username": "alice@example.com", "password": PASSWORD}
    )

    assert response.status_code == 401


# ---------------------------------------------------------- protected routes


async def test_me_returns_current_user(api_client: AsyncClient) -> None:
    created = await register(api_client)
    token = await login(api_client)

    response = await api_client.get("/api/v1/users/me", headers=bearer(token))

    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer not-a-token"}, {"Authorization": "Basic dXNlcjpwYXNz"}],
    ids=["missing", "garbage", "wrong-scheme"],
)
async def test_protected_route_requires_valid_token(
    api_client: AsyncClient, headers: dict[str, str]
) -> None:
    response = await api_client.get("/api/v1/users/me", headers=headers)

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "not_authenticated"


async def test_expired_token_is_rejected(api_client: AsyncClient, api_settings: Settings) -> None:
    created = await register(api_client)
    expired = create_access_token(
        uuid.UUID(str(created["id"])), api_settings, now=datetime.now(UTC) - timedelta(hours=1)
    )

    response = await api_client.get("/api/v1/users/me", headers=bearer(expired.token))

    assert response.status_code == 401


async def test_token_for_unknown_user_is_rejected(
    api_client: AsyncClient, api_settings: Settings
) -> None:
    token = create_access_token(uuid.uuid4(), api_settings).token

    response = await api_client.get("/api/v1/users/me", headers=bearer(token))

    assert response.status_code == 401


async def test_deactivation_takes_effect_before_token_expires(
    api_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await register(api_client)
    token = await login(api_client)
    await set_user(session_factory, "alice@example.com", is_active=False)

    response = await api_client.get("/api/v1/users/me", headers=bearer(token))

    assert response.status_code == 401


# --------------------------------------------------------------- access control


async def test_customer_cannot_list_users(api_client: AsyncClient) -> None:
    await register(api_client)
    token = await login(api_client)

    response = await api_client.get("/api/v1/users", headers=bearer(token))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


async def test_admin_can_list_users(
    api_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await register(api_client, email="admin@example.com")
    await register(api_client, email="bob@example.com")
    await set_user(session_factory, "admin@example.com", role=UserRole.ADMIN)
    token = await login(api_client, email="admin@example.com")

    response = await api_client.get("/api/v1/users?limit=10", headers=bearer(token))

    assert response.status_code == 200
    emails = {user["email"] for user in response.json()}
    assert emails == {"admin@example.com", "bob@example.com"}


async def test_role_change_takes_effect_immediately(
    api_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await register(api_client)
    token = await login(api_client)
    await set_user(session_factory, "alice@example.com", role=UserRole.ADMIN)

    response = await api_client.get("/api/v1/users", headers=bearer(token))

    assert response.status_code == 200
