"""Configuration is supplied through the AISEO_ environment namespace."""

from decimal import Decimal
from functools import lru_cache
from typing import Literal
from uuid import UUID

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
    llm_model: str = Field(default="gpt-4o-mini", min_length=1, max_length=80)
    llm_max_input_tokens: int = Field(default=8192, ge=128, le=100000)
    llm_max_output_tokens: int = Field(default=512, ge=32, le=8192)
    llm_max_total_tokens: int = Field(default=8704, ge=160, le=108192)
    llm_timeout_seconds: float = Field(default=15.0, ge=1, le=60)
    llm_max_retries: int = Field(default=2, ge=0, le=3)
    llm_concurrency: int = Field(default=3, ge=1, le=16)
    llm_input_usd_per_million: Decimal | None = Field(default=None, ge=0)
    llm_output_usd_per_million: Decimal | None = Field(default=None, ge=0)
    ai_meta_daily_usd_cap: Decimal = Field(default=Decimal("2.00"), gt=0, le=100)
    ai_meta_request_usd_cap: Decimal = Field(default=Decimal("0.05"), gt=0, le=5)
    rag_embedding_model: str = Field(default="text-embedding-3-small", min_length=2, max_length=120)
    rag_embedding_version: str = Field(default="v1", min_length=1, max_length=48)
    rag_chat_enabled: bool = False
    rag_chat_dev_token: SecretStr | None = None
    rag_chat_dev_owner_id: UUID | None = None
    # Explicit opt-in; no raw content or credentials are ever exported as span data.
    otel_traces_endpoint: str | None = None
    langfuse_host: str | None = None
    langfuse_public_key: SecretStr | None = None
    langfuse_secret_key: SecretStr | None = None
    audit_owner_daily_usd_cap: Decimal = Field(default=Decimal("0.50"), gt=0, le=100)
    ai_global_daily_usd_cap: Decimal = Field(default=Decimal("3.00"), gt=0, le=1000)
    audit_jobs_enabled: bool = False
    audit_dev_token: SecretStr | None = None
    audit_dev_owner_id: UUID | None = None
    audit_daily_job_cap: int = Field(default=12, ge=1, le=100)
    audit_daily_usd_cap: Decimal = Field(default=Decimal("1.00"), gt=0, le=100)
    audit_request_usd_cap: Decimal = Field(default=Decimal("0.30"), gt=0, le=10)
    rag_chat_embedding_usd_per_million: Decimal | None = Field(default=None, ge=0)
    rag_chat_daily_usd_cap: Decimal = Field(default=Decimal("1.00"), gt=0, le=100)
    rag_chat_request_usd_cap: Decimal = Field(default=Decimal("0.10"), gt=0, le=10)

    @model_validator(mode="after")
    def validate_production_storage(self) -> "Settings":
        if self.environment == "production" and (
            self.database_url is None or self.redis_url is None
        ):
            raise ValueError("Production requires AISEO_DATABASE_URL and AISEO_REDIS_URL")
        if self.llm_max_total_tokens < self.llm_max_output_tokens:
            raise ValueError("Total LLM token budget must cover output tokens")
        if (self.llm_input_usd_per_million is None) != (self.llm_output_usd_per_million is None):
            raise ValueError("Configure both LLM price rates or neither")
        if self.otel_traces_endpoint and not self.otel_traces_endpoint.startswith("https://"):
            raise ValueError("OTLP traces endpoint must use HTTPS")
        if self.langfuse_host and (
            not self.langfuse_host.startswith("https://")
            or self.langfuse_host.endswith("/api/public/otel/v1/traces")
        ):
            raise ValueError("Langfuse host must use an HTTPS base URL")
        configured_langfuse = (
            self.langfuse_host is not None,
            self.langfuse_public_key is not None,
            self.langfuse_secret_key is not None,
        )
        if any(configured_langfuse) and not all(configured_langfuse):
            raise ValueError("Langfuse requires host, public key and secret key together")
        if self.audit_jobs_enabled:
            if self.environment == "production":
                raise ValueError("Private audit job routes cannot be enabled in production")
            if (
                self.audit_dev_token is None
                or len(self.audit_dev_token.get_secret_value()) < 32
                or not self.audit_dev_token.get_secret_value().isascii()
                or self.audit_dev_owner_id is None
                or self.database_url is None
                or self.redis_url is None
            ):
                raise ValueError("Private audits require token, owner ID, PostgreSQL and Redis")
        if self.rag_chat_enabled:
            if self.environment == "production":
                raise ValueError("Private RAG chat cannot be enabled in production")
            if (
                self.rag_chat_dev_token is None
                or len(self.rag_chat_dev_token.get_secret_value()) < 32
                or not self.rag_chat_dev_token.get_secret_value().isascii()
                or self.rag_chat_dev_owner_id is None
            ):
                raise ValueError("Private RAG chat needs a 32+ character token and owner UUID")
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
