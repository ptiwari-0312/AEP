"""Typed, env-driven settings (docs/architecture/02-repo-design.md §2).

Every variable is read from the environment with an `AEP_` prefix
(docs/architecture/09-engineering-standards.md §3), e.g. `AEP_DATABASE_URL`.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AEP_", env_file=".env", extra="ignore")

    environment: str = "development"
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://aep:aep@localhost:5432/aep"
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60
    jwt_refresh_token_expire_days: int = 30

    github_oauth_client_id: str | None = None
    github_oauth_client_secret: str | None = None

    otel_service_name: str = "aep-backend"
    otel_exporter_otlp_endpoint: str | None = None


@lru_cache
def get_settings() -> Settings:
    """A FastAPI-dependency-shaped accessor, not a module-level constant — so tests can clear
    the cache (`get_settings.cache_clear()`) and construct a fresh `Settings()` against
    whatever environment they've set up, rather than fighting a singleton created at import
    time."""
    return Settings()
