"""Application settings, loaded from environment variables (and `.env` in local dev)."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

from app import __version__

Environment = Literal["local", "test", "staging", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Application ---
    app_name: str = "FinLedger API"
    app_version: str = __version__
    environment: Environment = "local"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"

    # --- Logging ---
    log_level: LogLevel = "INFO"
    log_json: bool = Field(
        default=False,
        description="Emit JSON logs (use in staging/production); pretty console logs otherwise.",
    )

    # --- PostgreSQL ---
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "finledger"
    postgres_password: SecretStr  # required: never hard-code credentials
    postgres_db: str = "finledger"
    db_pool_size: int = Field(default=5, ge=1)
    db_max_overflow: int = Field(default=10, ge=0)
    db_pool_timeout_seconds: int = Field(default=30, ge=1)
    db_echo: bool = False

    # --- Authentication (JWT) ---
    # Required, >= 32 chars. Generate one with:
    #   python -c "import secrets; print(secrets.token_urlsafe(48))"
    jwt_secret_key: SecretStr = Field(min_length=32)
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    jwt_issuer: str = "finledger-api"
    jwt_audience: str = "finledger-clients"
    access_token_expire_minutes: int = Field(default=15, ge=1, le=1440)

    @property
    def database_url(self) -> URL:
        """Async SQLAlchemy URL. `URL` masks the password when printed or logged."""
        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance. Override in tests via FastAPI dependency overrides."""
    return Settings()
