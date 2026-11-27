"""Shared FastAPI dependencies: settings, DB session, services and authentication."""

from collections.abc import Awaitable, Callable
from typing import Annotated

import structlog
from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import AuthenticationError, PermissionDeniedError
from app.core.security import TokenError, decode_access_token
from app.db.session import get_db_session
from app.models.user import User, UserRole
from app.repositories.users import UserRepository
from app.services.auth import AuthService


def get_app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
DbSessionDep = Annotated[AsyncSession, Depends(get_db_session)]


def get_auth_service(session: DbSessionDep, settings: SettingsDep) -> AuthService:
    return AuthService(session, settings)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]

# auto_error=False so missing tokens go through our own error envelope.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


async def get_current_user(
    token: Annotated[str | None, Depends(oauth2_scheme)],
    session: DbSessionDep,
    settings: SettingsDep,
) -> User:
    if not token:
        raise AuthenticationError()
    try:
        user_id = decode_access_token(token, settings)
    except TokenError:
        raise AuthenticationError("The access token is invalid or has expired.") from None

    # Reload on every request: disabling a user or changing their role takes effect
    # immediately instead of when their token expires.
    user = await UserRepository(session).get_by_id(user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("The access token is invalid or has expired.")

    structlog.contextvars.bind_contextvars(user_id=str(user.id))
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_role(*allowed: UserRole) -> Callable[[User], Awaitable[User]]:
    async def check_role(user: CurrentUser) -> User:
        if user.role not in allowed:
            raise PermissionDeniedError()
        return user

    return check_role


AdminUser = Annotated[User, Depends(require_role(UserRole.ADMIN))]
