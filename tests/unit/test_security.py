import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.core.security import (
    TokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    password_needs_rehash,
    verify_password,
)
from app.schemas.auth import RegisterRequest

# ------------------------------------------------------------------ passwords


def test_password_hash_is_argon2id_and_salted() -> None:
    first, second = hash_password("correct horse battery"), hash_password("correct horse battery")

    assert first.startswith("$argon2id$")
    assert "correct horse battery" not in first
    assert first != second  # random salt per hash


def test_verify_password() -> None:
    password_hash = hash_password("correct horse battery")

    assert verify_password(password_hash, "correct horse battery") is True
    assert verify_password(password_hash, "Correct horse battery") is False
    assert verify_password("not-a-valid-hash", "anything") is False
    assert password_needs_rehash(password_hash) is False


# --------------------------------------------------------------------- tokens


def test_access_token_round_trip(settings: Settings) -> None:
    user_id = uuid.uuid4()

    token = create_access_token(user_id, settings)

    assert decode_access_token(token.token, settings) == user_id
    assert token.expires_in == settings.access_token_expire_minutes * 60


def test_token_contains_standard_claims(settings: Settings) -> None:
    token = create_access_token(uuid.uuid4(), settings).token

    claims = jwt.decode(token, options={"verify_signature": False})

    assert {"sub", "exp", "iat", "nbf", "iss", "aud", "jti", "type"} <= claims.keys()
    assert claims["iss"] == settings.jwt_issuer
    assert claims["type"] == "access"


def test_expired_token_is_rejected(settings: Settings) -> None:
    an_hour_ago = datetime.now(UTC) - timedelta(hours=1)
    token = create_access_token(uuid.uuid4(), settings, now=an_hour_ago).token

    with pytest.raises(TokenError, match="expired"):
        decode_access_token(token, settings)


def test_token_signed_with_another_key_is_rejected(settings: Settings) -> None:
    attacker = settings.model_copy(update={"jwt_secret_key": SecretStr("x" * 40)})
    forged = create_access_token(uuid.uuid4(), attacker).token

    with pytest.raises(TokenError, match="Signature"):
        decode_access_token(forged, settings)


def test_tampered_token_is_rejected(settings: Settings) -> None:
    header, _payload, signature = create_access_token(uuid.uuid4(), settings).token.split(".")
    other_payload = create_access_token(uuid.uuid4(), settings).token.split(".")[1]

    with pytest.raises(TokenError):
        decode_access_token(f"{header}.{other_payload}.{signature}", settings)


def test_unsigned_alg_none_token_is_rejected(settings: Settings) -> None:
    claims = jwt.decode(
        create_access_token(uuid.uuid4(), settings).token, options={"verify_signature": False}
    )
    unsigned = jwt.encode(claims, key=None, algorithm="none")

    with pytest.raises(TokenError):
        decode_access_token(unsigned, settings)


@pytest.mark.parametrize(
    ("field", "value"),
    [("jwt_audience", "another-app"), ("jwt_issuer", "another-issuer")],
)
def test_token_for_another_audience_or_issuer_is_rejected(
    settings: Settings, field: str, value: str
) -> None:
    other = settings.model_copy(update={field: value})
    token = create_access_token(uuid.uuid4(), other).token

    with pytest.raises(TokenError):
        decode_access_token(token, settings)


def test_non_access_token_type_is_rejected(settings: Settings) -> None:
    claims = jwt.decode(
        create_access_token(uuid.uuid4(), settings).token, options={"verify_signature": False}
    )
    claims["type"] = "refresh"
    token = jwt.encode(claims, settings.jwt_secret_key.get_secret_value(), algorithm="HS256")

    with pytest.raises(TokenError, match="not an access token"):
        decode_access_token(token, settings)


def test_garbage_token_is_rejected(settings: Settings) -> None:
    with pytest.raises(TokenError):
        decode_access_token("not.a.jwt", settings)


def test_jwt_secret_must_be_long(settings: Settings) -> None:
    with pytest.raises(ValidationError, match="jwt_secret_key"):
        Settings(
            _env_file=None, postgres_password=SecretStr("x"), jwt_secret_key=SecretStr("short")
        )


# -------------------------------------------------------------------- schemas


def test_register_request_normalises_input() -> None:
    data = RegisterRequest(
        email="Alice.Smith@Example.COM",
        password=SecretStr("a-long-enough-password"),
        full_name="  Alice Smith ",
    )

    assert data.email == "alice.smith@example.com"
    assert data.full_name == "Alice Smith"
    assert "a-long-enough-password" not in repr(data)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("password", "short"),
        ("password", "x" * 129),
        ("email", "not-an-email"),
        ("full_name", "   "),
    ],
)
def test_register_request_rejects_invalid_input(field: str, value: str) -> None:
    payload = {
        "email": "alice@example.com",
        "password": "a-long-enough-password",
        "full_name": "Alice",
    }
    payload[field] = value

    with pytest.raises(ValidationError, match=field):
        RegisterRequest.model_validate(payload)
