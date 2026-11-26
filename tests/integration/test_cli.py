import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.cli import main
from app.core.config import Settings
from app.core.security import verify_password
from app.models.user import User, UserRole
from tests.integration.conftest import run_in_thread

pytestmark = pytest.mark.integration


async def _get_user(session_factory: async_sessionmaker[AsyncSession], email: str) -> User | None:
    async with session_factory() as session:
        return await session.scalar(select(User).where(User.email == email))


async def test_create_admin_creates_user_with_admin_role(
    api_settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    capsys: pytest.CaptureFixture[str],
) -> None:
    argv = ["create-admin", "--email", "Ops@Example.com", "--name", "Ops Admin"]

    exit_code = run_in_thread(
        lambda: main(argv, settings=api_settings, prompt_password=lambda: "a-strong-admin-pass")
    )

    assert exit_code == 0
    assert "Created admin ops@example.com" in capsys.readouterr().out
    user = await _get_user(session_factory, "ops@example.com")
    assert user is not None
    assert user.role is UserRole.ADMIN
    assert verify_password(user.password_hash, "a-strong-admin-pass")


async def test_create_admin_promotes_existing_user(
    api_settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session:
        session.add(User(email="bob@example.com", full_name="Bob", password_hash="x"))
        await session.commit()

    def no_prompt() -> str:
        raise AssertionError("must not ask for a password when promoting")

    argv = ["create-admin", "--email", "bob@example.com", "--name", "Bob"]
    assert run_in_thread(lambda: main(argv, settings=api_settings, prompt_password=no_prompt)) == 0

    user = await _get_user(session_factory, "bob@example.com")
    assert user is not None
    assert user.role is UserRole.ADMIN


def test_create_admin_rejects_weak_password(
    api_settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["create-admin", "--email", "weak@example.com", "--name", "Weak"]

    exit_code = run_in_thread(
        lambda: main(argv, settings=api_settings, prompt_password=lambda: "short")
    )

    assert exit_code == 1
    assert "password" in capsys.readouterr().out
