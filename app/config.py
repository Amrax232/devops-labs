"""Конфигурация приложения. Все параметры читаются из переменных окружения."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки приложения (см. .env.example)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "warehouse-inventory"
    app_env: str = "local"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"

    # Строка подключения к БД. Формат SQLAlchemy.
    database_url: str = "postgresql+psycopg2://warehouse:warehouse@localhost:5432/warehouse"

    # Показывать ли SQL-запросы в логах (удобно при отладке).
    sql_echo: bool = False


@lru_cache
def get_settings() -> Settings:
    """Настройки кэшируются: один объект на процесс."""
    return Settings()
