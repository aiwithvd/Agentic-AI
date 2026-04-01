"""Application-wide settings loaded from environment / .env file."""

from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic import AnyUrl, Field, PostgresDsn, RedisDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed settings sourced from environment variables or .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # LLM
    anthropic_api_key: str = Field(..., description="Anthropic API key")

    # Database — SQLAlchemy async engine (postgresql+asyncpg://...)
    database_url: PostgresDsn = Field(
        ..., description="Async PostgreSQL DSN for SQLAlchemy"
    )
    # LangGraph checkpointer uses plain postgresql:// (its own internal pool)
    checkpoint_database_url: AnyUrl = Field(
        ..., description="Plain PostgreSQL DSN for LangGraph AsyncPostgresSaver"
    )
    db_pool_size: int = Field(default=10)
    db_max_overflow: int = Field(default=20)
    db_pool_timeout: int = Field(default=30)

    # Redis
    redis_url: RedisDsn = Field(..., description="Redis DSN (redis://...)")
    redis_max_connections: int = Field(default=50)

    # Rate limiting
    rate_limit_requests: int = Field(default=60)
    rate_limit_window_seconds: int = Field(default=60)

    # Response caching
    cache_ttl_seconds: int = Field(default=300)

    # App
    app_env: str = Field(default="development")
    log_level: str = Field(default="INFO")
    cors_origins: List[str] = Field(default_factory=lambda: ["http://localhost:3000"])


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton Settings instance."""
    return Settings()  # type: ignore[call-arg]
