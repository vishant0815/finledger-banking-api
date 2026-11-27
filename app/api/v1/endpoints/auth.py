from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.deps import AuthServiceDep
from app.schemas.auth import RegisterRequest, TokenResponse
from app.schemas.errors import ErrorResponse
from app.schemas.users import UserRead

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    summary="Register a customer account",
    responses={status.HTTP_409_CONFLICT: {"model": ErrorResponse}},
)
async def register(body: RegisterRequest, auth: AuthServiceDep) -> UserRead:
    user = await auth.register(body)
    return UserRead.model_validate(user)


@router.post(
    "/login",
    summary="Log in and receive a JWT access token",
    description=(
        "OAuth2 password flow: send `username` (your email) and `password` as form "
        "data. Use the returned token as `Authorization: Bearer <token>`."
    ),
    responses={status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse}},
)
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()], auth: AuthServiceDep
) -> TokenResponse:
    user = await auth.authenticate(form.username, form.password)
    token = auth.issue_access_token(user)
    return TokenResponse(access_token=token.token, expires_in=token.expires_in)
