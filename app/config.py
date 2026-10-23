"""Конфигурация приложения. Все параметры читаются из переменных окружения."""

import socket
from functools import lru_cache

from pydantic import Field
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
    # По умолчанию слушаем только локальный интерфейс; на сервере адрес задаётся
    # явно через APP_HOST (см. deploy/app/warehouse.env.example).
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    log_level: str = "INFO"

    # Идентификатор экземпляра приложения: возвращается в заголовке X-Instance-Id
    # и в /healthz, чтобы при нескольких экземплярах за балансировщиком было видно,
    # кто обработал запрос. В контейнерах задаётся через INSTANCE_ID.
    instance_id: str = Field(default_factory=socket.gethostname)

    # Строка подключения к БД. Формат SQLAlchemy.
    database_url: str = "postgresql+psycopg2://warehouse:warehouse@localhost:5432/warehouse"

    # Показывать ли SQL-запросы в логах (удобно при отладке).
    sql_echo: bool = False

    # Учётная запись для доступа к API (HTTP Basic). Пароль по умолчанию
    # намеренно не задан: без AUTH_PASSWORD в окружении приложение не запустится.
    auth_username: str = "admin"
    auth_password: str


@lru_cache
def get_settings() -> Settings:
    """Настройки кэшируются: один объект на процесс."""
    return Settings()
