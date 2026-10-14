"""Configuration is supplied through the AISEO_ environment namespace."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AISEO_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "AISEOOnline API"
    environment: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    api_port: int = Field(default=8000, ge=1, le=65535)
    database_url: SecretStr | None = None
    redis_url: SecretStr | None = None
    openai_api_key: SecretStr | None = None

    @model_validator(mode="after")
    def validate_production_storage(self) -> "Settings":
        if self.environment == "production" and (
            self.database_url is None or self.redis_url is None
        ):
            raise ValueError("Production requires AISEO_DATABASE_URL and AISEO_REDIS_URL")
        return self

    def require_database_url(self) -> str:
        if self.database_url is None:
            raise RuntimeError("AISEO_DATABASE_URL is required for database operations")
        return self.database_url.get_secret_value()

    def require_redis_url(self) -> str:
        if self.redis_url is None:
            raise RuntimeError("AISEO_REDIS_URL is required for queue and cache operations")
        return self.redis_url.get_secret_value()


@lru_cache
def get_settings() -> Settings:
    return Settings()
