"""Простейшая аутентификация: HTTP Basic с одной учётной записью.

Логин и пароль берутся из переменных окружения AUTH_USERNAME и AUTH_PASSWORD
(см. .env.example) и в репозитории не хранятся.
"""

import secrets

from fastapi import Depends
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.config import Settings, get_settings
from app.errors import AuthError

# auto_error=False: отсутствие заголовка обрабатываем сами, чтобы ошибка
# возвращалась в том же формате, что и остальные ответы приложения.
basic_scheme = HTTPBasic(auto_error=False)


def require_auth(
    credentials: HTTPBasicCredentials | None = Depends(basic_scheme),
    settings: Settings = Depends(get_settings),
) -> str:
    """Зависимость: пускает дальше только с правильными логином и паролем."""
    if credentials is None:
        raise AuthError("Требуется вход: укажите логин и пароль")

    # compare_digest сравнивает строки за постоянное время: по скорости ответа
    # нельзя подобрать пароль посимвольно.
    username_ok = secrets.compare_digest(credentials.username, settings.auth_username)
    password_ok = secrets.compare_digest(credentials.password, settings.auth_password)
    if not (username_ok and password_ok):
        raise AuthError("Неверный логин или пароль")

    return credentials.username
