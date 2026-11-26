from typing import Literal

from pydantic import BaseModel, EmailStr, Field, SecretStr, field_validator

PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 128  # bounds hashing cost per request


class RegisterRequest(BaseModel):
    email: EmailStr = Field(examples=["alice@example.com"])
    # SecretStr keeps the password out of reprs, logs and tracebacks.
    password: SecretStr = Field(
        min_length=PASSWORD_MIN_LENGTH,
        max_length=PASSWORD_MAX_LENGTH,
        examples=["correct-horse-battery-staple"],
    )
    full_name: str = Field(min_length=1, max_length=100, examples=["Alice Smith"])

    @field_validator("email")
    @classmethod
    def normalise_email(cls, value: str) -> str:
        return value.lower()

    @field_validator("full_name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 - OAuth2 token type, not a secret
    expires_in: int = Field(description="Seconds until the access token expires.", examples=[900])
