"""Структурированные журналы и маскирование секретов (app/logging_setup.py).

Модуль не зависит от FastAPI и базы, поэтому проверяется unit-тестами.
"""

import io
import json
import logging

import pytest

from app.logging_setup import MASK, JsonFormatter, SecretMasker, request_id_var

SECRET = "SuperSecret123"


def _format(message: str, *args: object, **extra: object) -> dict:
    masker = SecretMasker([SECRET])
    formatter = JsonFormatter(masker, {"instance": "app-1", "version": "1.0"})
    record = logging.makeLogRecord(
        {"name": "app.test", "levelname": "INFO", "levelno": 20, "msg": message, "args": args}
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return json.loads(formatter.format(record))


def test_record_has_required_fields() -> None:
    token = request_id_var.set("req-1")
    try:
        entry = _format(
            "GET /api/v1/units → 200",
            event="http_request",
            endpoint="/api/v1/units",
            status=200,
            result="ok",
            duration_ms=1.5,
        )
    finally:
        request_id_var.reset(token)
    for field in ("time", "level", "event", "message", "request_id", "instance", "version"):
        assert field in entry
    assert entry["event"] == "http_request"
    assert entry["endpoint"] == "/api/v1/units"
    assert entry["status"] == 200 and entry["result"] == "ok"
    assert entry["request_id"] == "req-1"
    assert entry["time"].endswith("+00:00")


def test_request_id_defaults_to_dash_outside_request() -> None:
    assert _format("старт")["request_id"] == "-"


@pytest.mark.parametrize(
    ("message", "leaked"),
    [
        (f"вход с паролем {SECRET}", SECRET),
        ("password=hunter2-long user=admin", "hunter2-long"),
        ('{"token": "test-password-77"}', "test-password-77"),
        ("Authorization: Basic YWRtaW46c2VjcmV0", "YWRtaW46c2VjcmV0"),
        ("dsn postgresql+psycopg2://warehouse:pg-pass-777@db:5432/warehouse", "pg-pass-777"),
        ("token ghp_" + "a" * 36, "ghp_" + "a" * 36),
    ],
)
def test_secrets_are_masked(message: str, leaked: str) -> None:
    entry = _format(message)
    assert leaked not in json.dumps(entry, ensure_ascii=False)
    assert MASK in entry["message"]


def test_secret_in_extra_field_is_masked() -> None:
    entry = _format("ошибка подключения", details={"url": f"https://user:{SECRET}@host/"})
    assert SECRET not in json.dumps(entry, ensure_ascii=False)


def test_every_masking_is_reported() -> None:
    masker = SecretMasker([SECRET])
    seen: list[int] = []
    masker.on_redaction.append(seen.append)
    assert masker(f"a {SECRET} b") == f"a {MASK} b"
    assert masker("обычный текст про политику паролей") == "обычный текст про политику паролей"
    assert seen == [1]


def test_short_values_are_not_treated_as_secrets() -> None:
    assert SecretMasker(["admin"])("user admin logged in") == "user admin logged in"


def test_configure_logging_writes_json_lines() -> None:
    from app.logging_setup import configure_logging

    stream = io.StringIO()
    root = logging.getLogger()
    saved = root.handlers[:], root.level
    try:
        configure_logging("INFO", secrets=[SECRET], static={"instance": "t"}, stream=stream)
        logging.getLogger("app.test").info("пароль %s", SECRET, extra={"event": "probe"})
    finally:
        root.handlers, level = saved
        root.setLevel(level)
    entry = json.loads(stream.getvalue().splitlines()[-1])
    assert entry["event"] == "probe" and SECRET not in entry["message"]
    assert logging.getLogger("uvicorn.access").disabled
