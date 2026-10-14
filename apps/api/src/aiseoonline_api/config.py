"""Validated runtime configuration loaded from environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
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
    openai_api_key: SecretStr | None = None


@lru_cache
def get_settings() -> Settings:
    """Cache settings for the process; override the factory dependency in tests."""
    return Settings()
