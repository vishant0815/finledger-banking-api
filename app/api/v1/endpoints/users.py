from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import AdminUser, CurrentUser, DbSessionDep
from app.repositories.users import UserRepository
from app.schemas.errors import ErrorResponse
from app.schemas.users import UserRead

router = APIRouter(
    prefix="/users",
    tags=["users"],
    responses={status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse}},
)


@router.get("/me", summary="Get the current user")
async def read_current_user(user: CurrentUser) -> UserRead:
    return UserRead.model_validate(user)


@router.get(
    "",
    summary="List users (admin only)",
    responses={status.HTTP_403_FORBIDDEN: {"model": ErrorResponse}},
)
async def list_users(
    _: AdminUser,
    session: DbSessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[UserRead]:
    users = await UserRepository(session).list_users(limit=limit, offset=offset)
    return [UserRead.model_validate(user) for user in users]
