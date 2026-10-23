# Образ приложения «Складской учёт» (ЛР4).
#
# Сборка в два этапа:
#   builder — виртуальное окружение с зависимостями (компиляторы и кэш pip
#             в итоговый образ не попадают);
#   runtime — только интерпретатор, окружение и код; запуск не от root.
#
# Воспроизводимость: базовый образ закреплён точной версией, версии всех
# зависимостей (включая транзитивные) — файлом requirements.lock (make lock).
# Секретов в образе нет: логин, пароль и строка подключения к БД передаются
# переменными окружения при запуске контейнера (docker-compose.yml, .env).

ARG PYTHON_IMAGE=python:3.12.7-slim-bookworm

# ------------------------------------------------------------------ builder
FROM ${PYTHON_IMAGE} AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH=/opt/venv/bin:$PATH

RUN python -m venv /opt/venv

WORKDIR /build
COPY requirements.txt requirements.lock ./
# -c requirements.lock: точные версии транзитивных зависимостей — образ,
# собранный сегодня и через месяц, содержит одни и те же пакеты.
RUN pip install -r requirements.txt -c requirements.lock

# ------------------------------------------------------------------ runtime
FROM ${PYTHON_IMAGE} AS runtime

ARG APP_VERSION=0.7.0
# коммит и репозиторий, из которых собран образ (передаёт CI)
ARG VCS_REF=local
ARG SOURCE_URL=""
LABEL org.opencontainers.image.title="warehouse-inventory" \
      org.opencontainers.image.description="Складской учёт: FastAPI + PostgreSQL" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.source="${SOURCE_URL}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH \
    APP_ENV=container

# Отдельный системный пользователь без домашнего каталога и оболочки входа.
# UID/GID фиксированы (10001), чтобы права не зависели от порядка создания
# пользователей в базовом образе.
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home \
       --home-dir /nonexistent --shell /usr/sbin/nologin app

COPY --from=builder /opt/venv /opt/venv

# Код принадлежит root и доступен приложению только на чтение.
WORKDIR /app
COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app
COPY scripts/seed.py ./scripts/seed.py

USER 10001:10001

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"]

# SIGTERM (docker stop) → uvicorn перестаёт принимать соединения, дожидается
# текущих запросов (не дольше 15 с) и завершается сам, без SIGKILL.
STOPSIGNAL SIGTERM

# exec-форма: uvicorn — прямой потомок init-процесса и сам получает сигналы
# (оболочка sh -c между ними сигнал бы не передала).
# --timeout-keep-alive 65 больше, чем keepalive_timeout у nginx (30 с): простаивающее
# соединение закрывает nginx, а не приложение — без гонки «запрос в закрытое соединение».
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--no-server-header", \
     "--timeout-keep-alive", "65", \
     "--timeout-graceful-shutdown", "15"]
