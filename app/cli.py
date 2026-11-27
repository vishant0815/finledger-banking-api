"""Operational commands.

    uv run python -m app.cli create-admin --email admin@example.com --name "Ops Admin"
    docker compose run --rm api python -m app.cli create-admin --email ... --name ...

The password is read interactively (never from argv, which ends up in shell
history and process listings). An existing user with that email is promoted.
"""

import argparse
import asyncio
import getpass
import sys
from collections.abc import Callable, Sequence

from pydantic import SecretStr, ValidationError

from app.core.config import Settings, get_settings
from app.db.session import create_db_engine, create_session_factory
from app.models.user import UserRole
from app.repositories.users import UserRepository
from app.schemas.auth import RegisterRequest
from app.services.auth import AuthService


async def create_admin(
    settings: Settings, email: str, full_name: str, prompt_password: Callable[[], str]
) -> str:
    engine = create_db_engine(settings)
    try:
        async with create_session_factory(engine)() as session:
            existing = await UserRepository(session).get_by_email(email)
            if existing is not None:
                existing.role = UserRole.ADMIN
                await session.commit()
                return f"Promoted existing user {existing.email} to admin."

            data = RegisterRequest(
                email=email, full_name=full_name, password=SecretStr(prompt_password())
            )
            user = await AuthService(session, settings).register(data, role=UserRole.ADMIN)
            return f"Created admin {user.email} ({user.id})."
    finally:
        await engine.dispose()


def _prompt_password() -> str:
    password = getpass.getpass("Password (min 12 characters): ")
    if password != getpass.getpass("Repeat password: "):
        raise SystemExit("Passwords do not match.")
    return password


def main(
    argv: Sequence[str] | None = None,
    *,
    settings: Settings | None = None,
    prompt_password: Callable[[], str] = _prompt_password,
) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="FinLedger admin tools")
    commands = parser.add_subparsers(dest="command", required=True)
    admin = commands.add_parser("create-admin", help="create an admin user or promote one")
    admin.add_argument("--email", required=True)
    admin.add_argument("--name", required=True, help="full name")
    args = parser.parse_args(argv)

    try:
        message = asyncio.run(
            create_admin(settings or get_settings(), args.email, args.name, prompt_password)
        )
    except ValidationError as exc:
        print(f"Invalid input: {exc.errors()[0]['loc'][0]}: {exc.errors()[0]['msg']}")
        return 1
    print(message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
