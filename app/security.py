"""Разграничение прав доступа (HTTP Basic, одна учётная запись).

Правило простое:
- **читать** данные (GET, HEAD, OPTIONS) может любой, даже без входа;
- **добавлять, изменять и удалять** (POST, PUT, PATCH, DELETE) — только после
  входа с логином и паролем.

Логин и пароль берутся из переменных окружения AUTH_USERNAME и AUTH_PASSWORD
(см. .env.example) и в репозитории не хранятся.
"""

import secrets

from fastapi import Depends, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.config import Settings, get_settings
from app.errors import AuthError

# Методы, которые только читают данные и ничего не меняют.
READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# auto_error=False: отсутствие заголовка обрабатываем сами, чтобы ошибка
# возвращалась в том же формате, что и остальные ответы приложения.
basic_scheme = HTTPBasic(auto_error=False)


def require_auth(
    credentials: HTTPBasicCredentials | None = Depends(basic_scheme),
    settings: Settings = Depends(get_settings),
) -> str:
    """Пускает дальше только с правильными логином и паролем."""
    if credentials is None:
        raise AuthError("Требуется вход: укажите логин и пароль")

    # compare_digest сравнивает строки за постоянное время: по скорости ответа
    # нельзя подобрать пароль посимвольно.
    username_ok = secrets.compare_digest(credentials.username, settings.auth_username)
    password_ok = secrets.compare_digest(credentials.password, settings.auth_password)
    if not (username_ok and password_ok):
        raise AuthError("Неверный логин или пароль")

    return credentials.username


def require_auth_for_changes(
    request: Request,
    credentials: HTTPBasicCredentials | None = Depends(basic_scheme),
    settings: Settings = Depends(get_settings),
) -> str | None:
    """Чтение — всем, изменение данных — только после входа.

    Возвращает имя пользователя или None для анонимного чтения. Если логин и
    пароль переданы, они проверяются при любом запросе, в том числе при чтении:
    неверные учётные данные не превращаются молча в анонимный доступ.
    """
    if credentials is None and request.method in READ_METHODS:
        return None
    return require_auth(credentials, settings)
