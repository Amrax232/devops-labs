"""Тестовая конфигурация, общая для всех уровней тестов.

Здесь только окружение — никаких импортов приложения. Благодаря этому
unit-тесты (tests/unit) не поднимают FastAPI и базу и работают быстро, что
важно для мутационного тестирования: тесты запускаются для каждого мутанта.

Изоляция от рабочих данных:
- приложение в тестах получает собственную SQLite-базу во временном каталоге,
  уникальном для каждого запуска pytest;
- интеграционные тесты работают с отдельной базой PostgreSQL, имя которой
  обязано оканчиваться на «_test» (см. tests/integration/conftest.py);
- логин и пароль API в тестах свои и не совпадают с рабочими.
"""

import atexit
import os
import shutil
import tempfile
from pathlib import Path

_TMP_DIR = Path(tempfile.mkdtemp(prefix="warehouse-tests-"))
atexit.register(shutil.rmtree, _TMP_DIR, ignore_errors=True)

# Переменные выставляются до импорта приложения: конфигурация читается при импорте.
# Значения из .env и окружения разработчика намеренно перекрываются.
os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{_TMP_DIR / 'app.sqlite3'}"
os.environ["APP_ENV"] = "test"
os.environ["AUTH_USERNAME"] = "tester"
os.environ["AUTH_PASSWORD"] = "test-password"
os.environ["INSTANCE_ID"] = "test-instance"
