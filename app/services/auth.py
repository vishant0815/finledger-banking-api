"""Registration and login."""

import asyncio

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import AuthenticationError, ConflictError
from app.core.logging import get_logger
from app.core.security import (
    AccessToken,
    create_access_token,
    hash_password,
    password_needs_rehash,
    verify_dummy_password,
    verify_password,
)
from app.db.errors import violated_constraint
from app.models.user import User, UserRole
from app.repositories.users import UserRepository
from app.schemas.auth import RegisterRequest

logger = get_logger("finledger.auth")


class EmailAlreadyRegisteredError(ConflictError):
    code = "email_already_registered"
    message = "An account with this email address already exists."


class InvalidCredentialsError(AuthenticationError):
    code = "invalid_credentials"
    # Deliberately vague: never reveal whether the email or the password was wrong.
    message = "Incorrect email or password."


class AuthService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.users = UserRepository(session)

    async def register(self, data: RegisterRequest, *, role: UserRole = UserRole.CUSTOMER) -> User:
        if await self.users.get_by_email(data.email) is not None:
            raise EmailAlreadyRegisteredError()

        # Argon2 is deliberately slow (CPU + memory); keep it off the event loop.
        password_hash = await asyncio.to_thread(hash_password, data.password.get_secret_value())
        user = User(
            email=data.email, full_name=data.full_name, password_hash=password_hash, role=role
        )
        try:
            await self.users.add(user)
            await self.session.commit()
        except IntegrityError as exc:
            # Two concurrent sign-ups with the same email can both pass the check
            # above; the unique constraint decides the winner.
            await self.session.rollback()
            if violated_constraint(exc) == "uq_users_email":
                raise EmailAlreadyRegisteredError() from exc
            raise

        logger.info("user.registered", user_id=str(user.id), role=user.role.value)
        return user

    async def authenticate(self, email: str, password: str) -> User:
        user = await self.users.get_by_email(email)
        if user is None:
            await asyncio.to_thread(verify_dummy_password, password)
            logger.info("auth.login_failed", reason="unknown_email")
            raise InvalidCredentialsError()

        valid = await asyncio.to_thread(verify_password, user.password_hash, password)
        if not valid or not user.is_active:
            reason = "inactive_user" if valid else "wrong_password"
            logger.info("auth.login_failed", reason=reason, user_id=str(user.id))
            raise InvalidCredentialsError()

        if password_needs_rehash(user.password_hash):
            user.password_hash = await asyncio.to_thread(hash_password, password)
            await self.session.commit()

        logger.info("auth.login_succeeded", user_id=str(user.id))
        return user

    def issue_access_token(self, user: User) -> AccessToken:
        return create_access_token(user.id, self.settings)
