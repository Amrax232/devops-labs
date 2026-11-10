"""Структурированные журналы (ЛР8): одна запись — одна строка JSON.

Каждая запись содержит время (UTC), уровень, тип события, источник, сообщение,
идентификатор запроса и экземпляр; запись о HTTP-запросе — ещё метод, адрес
операции (шаблон маршрута), код ответа, результат и длительность.

Секреты в журнал не попадают: перед выводом каждое строковое поле проходит
через маскирование — известные значения паролей из настроек и типичные формы
секретов (password=…, Authorization: Basic …, токены, пароль в строке
подключения) заменяются на «***». Каждое срабатывание учитывается в метрике
warehouse_log_secrets_redacted_total: появление секрета в журнале — повод для
оповещения, даже если он замаскирован.

Модуль не зависит от FastAPI и базы данных: его проверяют unit-тесты.
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Any

MASK = "***"

# идентификатор текущего запроса: попадает во все записи, сделанные при его обработке
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

# типичные формы секретов; значение заменяется, имя поля остаётся для диагностики
SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Authorization: Basic/Bearer <значение>
    (
        re.compile(r"(?i)\b(authorization\s*[:=]\s*[\"']?(?:basic|bearer)\s+)[^\s\"',;]+"),
        r"\1" + MASK,
    ),
    # password=…, "password": "…", token: …, secret=…, api_key=…
    (
        re.compile(
            r"(?i)(\b[\w-]*(?:password|passwd|secret|token|api[_-]?key)[\"']?\s*[:=]\s*[\"']?)"
            r"(?!\*\*\*)[^\s\"',;&}]+"
        ),
        r"\1" + MASK,
    ),
    # пароль в строке подключения: scheme://user:password@host
    (re.compile(r"(://[^:/@\s]+:)(?!\*\*\*@)[^@/\s]+(@)"), r"\1" + MASK + r"\2"),
    # токены GitHub
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"), MASK),
]

# Поля записи, которые не выводятся отдельно (служебные атрибуты LogRecord)
_RESERVED = set(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


class SecretMasker:
    """Заменяет секреты в строках на «***» и сообщает о каждом срабатывании."""

    def __init__(self, secrets: Iterable[str] = ()) -> None:
        # слишком короткие значения не маскируются: «admin» встретится где угодно
        self.secrets = sorted({s for s in secrets if s and len(s) >= 6}, key=len, reverse=True)
        self.on_redaction: list[Callable[[int], None]] = []

    def __call__(self, text: str) -> str:
        found = 0
        for secret in self.secrets:
            if secret in text:
                found += text.count(secret)
                text = text.replace(secret, MASK)
        for pattern, replacement in SECRET_PATTERNS:
            text, count = pattern.subn(replacement, text)
            found += count
        if found:
            for callback in self.on_redaction:
                callback(found)
        return text


class JsonFormatter(logging.Formatter):
    """Запись журнала → строка JSON с обязательными полями."""

    def __init__(self, masker: SecretMasker, static: dict[str, str] | None = None) -> None:
        super().__init__()
        self.masker = masker
        self.static = static or {}

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "event": getattr(record, "event", "log"),
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None) or request_id_var.get(),
            **self.static,
        }
        for key, value in vars(record).items():
            if key not in _RESERVED and key not in entry and not key.startswith("_"):
                entry[key] = value
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(self._mask(entry), ensure_ascii=False, default=str)

    def _mask(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.masker(value)
        if isinstance(value, dict):
            return {key: self._mask(item) for key, item in value.items()}
        if isinstance(value, list | tuple):
            return [self._mask(item) for item in value]
        return value


def configure_logging(
    level: str = "INFO",
    *,
    secrets: Iterable[str] = (),
    static: dict[str, str] | None = None,
    stream: Any = None,
) -> SecretMasker:
    """Направляет все журналы (приложения и uvicorn) в один JSON-обработчик.

    Журнал доступа uvicorn отключается: каждый запрос записывает middleware
    приложения (событие http_request) — с адресом операции и request_id.
    """
    masker = SecretMasker(secrets)
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(JsonFormatter(masker, static))

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    for name in ("uvicorn", "uvicorn.error"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True
    logging.getLogger("uvicorn.access").disabled = True
    return masker
