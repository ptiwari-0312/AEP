from __future__ import annotations

from aep.core.config import Settings, get_settings


def test_get_settings_is_cached() -> None:
    get_settings.cache_clear()
    first = get_settings()
    second = get_settings()
    assert first is second


def test_settings_reads_env_prefix(monkeypatch) -> None:
    monkeypatch.setenv("AEP_DATABASE_URL", "postgresql+psycopg://test:test@localhost/testdb")
    monkeypatch.setenv("AEP_LOG_LEVEL", "DEBUG")
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.database_url == "postgresql+psycopg://test:test@localhost/testdb"
    assert settings.log_level == "DEBUG"
    get_settings.cache_clear()


def test_settings_has_sensible_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.environment == "development"
    assert settings.jwt_algorithm == "HS256"
    assert settings.otel_exporter_otlp_endpoint is None
