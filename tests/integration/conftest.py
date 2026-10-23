"""Интеграционные тесты: настоящий PostgreSQL и настоящие миграции Alembic.

Тестовая база отделена от рабочей: по умолчанию это warehouse_test на том же
сервере, который поднимает `make dev-db` (порт на 127.0.0.1). Адрес можно
переопределить переменной TEST_DATABASE_URL (в окружении или в .env).

Защита рабочих данных: тесты удаляют и пересоздают схему перед каждым тестом,
поэтому они отказываются запускаться на базе, имя которой не оканчивается
на «_test». Случайно указать рабочую базу и стереть её не получится.
"""

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

ROOT = Path(__file__).resolve().parents[2]
AUTH = ("tester", "test-password")


class IntegrationSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    test_database_url: str = (
        "postgresql+psycopg2://warehouse:warehouse@localhost:5432/warehouse_test"
    )


def _ensure_database_exists(url: str) -> None:
    target = make_url(url)
    name = target.database or ""
    if not re.fullmatch(r"[a-z0-9_]+_test", name):
        pytest.exit(
            f"Интеграционные тесты работают только с базой *_test, а указана «{name}». "
            "Проверьте TEST_DATABASE_URL.",
            returncode=2,
        )
    admin = create_engine(target.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            exists = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": name}
            ).scalar()
            if not exists:
                # имя проверено регулярным выражением выше, подстановка безопасна
                connection.execute(text(f'CREATE DATABASE "{name}"'))
    except OperationalError as error:
        pytest.exit(
            f"PostgreSQL недоступен ({target.host}:{target.port}). "
            f"Поднимите базу: make dev-db. Подробности: {error.orig}",
            returncode=2,
        )
    finally:
        admin.dispose()


@pytest.fixture(scope="session")
def database_url() -> str:
    url = IntegrationSettings().test_database_url
    _ensure_database_exists(url)
    return url


@pytest.fixture
def engine(database_url: str) -> Iterator[Engine]:
    """Пустая база: схема public удаляется и создаётся заново перед каждым тестом."""
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    yield engine
    engine.dispose()


@pytest.fixture
def alembic_cfg(database_url: str) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    # ConfigParser воспринимает «%» как подстановку — экранируем
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


@pytest.fixture
def migrated_engine(engine: Engine, alembic_cfg: Config) -> Engine:
    """База, приведённая миграциями к последней версии схемы."""
    command.upgrade(alembic_cfg, "head")
    return engine


@pytest.fixture
def pg_client(migrated_engine: Engine) -> Iterator[TestClient]:
    """HTTP-клиент приложения, работающего с тестовой базой PostgreSQL."""
    from app.db import get_db
    from app.main import app

    factory = sessionmaker(bind=migrated_engine, autoflush=False)

    def override_get_db() -> Iterator[Session]:
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            client.auth = AUTH
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)
