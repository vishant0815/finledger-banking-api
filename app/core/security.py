"""Password hashing (Argon2id) and JWT access tokens (PyJWT)."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import Settings

# argon2-cffi defaults follow RFC 9106's recommended Argon2id profile.
_hasher = PasswordHasher()

ACCESS_TOKEN_TYPE = "access"  # noqa: S105 - a claim value, not a secret


# ------------------------------------------------------------------- passwords


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    """True if the hash was made with weaker parameters than the current ones."""
    return _hasher.check_needs_rehash(password_hash)


@lru_cache
def _dummy_hash() -> str:
    return _hasher.hash("timing-equaliser-not-a-real-password")


def verify_dummy_password(password: str) -> None:
    """Spend the same time as a real check when the user doesn't exist.

    Without this, "unknown email" answers faster than "wrong password", and an
    attacker could use response times to discover which emails are registered.
    """
    verify_password(_dummy_hash(), password)


# ----------------------------------------------------------------------- tokens


class TokenError(Exception):
    """The token is missing, malformed, expired, or was not issued by us."""


@dataclass(frozen=True, slots=True)
class AccessToken:
    token: str
    expires_in: int  # seconds


def create_access_token(
    subject: uuid.UUID, settings: Settings, *, now: datetime | None = None
) -> AccessToken:
    issued_at = now or datetime.now(UTC)
    lifetime = timedelta(minutes=settings.access_token_expire_minutes)
    claims = {
        "sub": str(subject),
        "type": ACCESS_TOKEN_TYPE,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": issued_at,
        "nbf": issued_at,
        "exp": issued_at + lifetime,
        "jti": uuid.uuid4().hex,  # unique ID: enables revocation lists later
    }
    token = jwt.encode(
        claims, settings.jwt_secret_key.get_secret_value(), algorithm=settings.jwt_algorithm
    )
    return AccessToken(token=token, expires_in=int(lifetime.total_seconds()))


def decode_access_token(token: str, settings: Settings) -> uuid.UUID:
    """Validate signature, expiry, issuer and audience; return the user ID."""
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],  # pinned: rejects "alg": "none" and swaps
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={"require": ["sub", "exp", "iat", "nbf", "iss", "aud", "jti"]},
            leeway=timedelta(seconds=5),
        )
    except jwt.InvalidTokenError as exc:
        raise TokenError(str(exc)) from exc

    if claims.get("type") != ACCESS_TOKEN_TYPE:
        raise TokenError("not an access token")
    try:
        return uuid.UUID(claims["sub"])
    except (ValueError, TypeError) as exc:
        raise TokenError("invalid subject") from exc
