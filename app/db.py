"""Подключение к базе данных и сессии SQLAlchemy."""

import sqlite3
from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    """Базовый класс для всех ORM-моделей."""


def _engine_kwargs(url: str) -> dict:
    # SQLite используется только в тестах и требует отдельного флага.
    if url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}
    return {"pool_pre_ping": True}


settings = get_settings()
engine = create_engine(
    settings.database_url,
    echo=settings.sql_echo,
    **_engine_kwargs(settings.database_url),
)


@event.listens_for(engine, "connect")
def _register_sqlite_unicode_lower(dbapi_connection, connection_record) -> None:
    """Регистрирует unicode-aware lower() для SQLite.

    Встроенная в SQLite функция lower() умеет только ASCII, поэтому
    поиск без учёта регистра по кириллице (ILIKE) не работает.
    Подменяем её Python-реализацией. В PostgreSQL такой проблемы нет,
    поэтому патч применяется только к соединениям SQLite.
    """
    if isinstance(dbapi_connection, sqlite3.Connection):
        dbapi_connection.create_function(
            "lower", 1, lambda value: value.lower() if isinstance(value, str) else value
        )


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    """Зависимость FastAPI: сессия БД на один HTTP-запрос."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()