"""Точка входа приложения «Складской учёт»."""

import logging
import re
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request, Response
from sqlalchemy.engine import make_url
from starlette.routing import Match

from app import __version__, metrics
from app.config import get_settings
from app.db import engine
from app.errors import register_error_handlers
from app.logging_setup import configure_logging, request_id_var
from app.routers import health, materials, receipts, reports, suppliers, units
from app.security import require_auth_for_changes

settings = get_settings()

# Структурированные журналы: JSON, request_id, маскирование секретов из настроек
masker = configure_logging(
    settings.log_level,
    secrets=[settings.auth_password, make_url(settings.database_url).password or ""],
    static={"instance": settings.instance_id, "version": __version__},
)
masker.on_redaction.append(metrics.SECRETS_REDACTED.inc)
metrics.APP_INFO.labels(
    __version__, settings.app_revision, settings.instance_id, settings.app_env
).set(1)

logger = logging.getLogger(__name__)
access_logger = logging.getLogger("app.access")

# служебные адреса опрашиваются постоянно — их запросы пишутся на уровне DEBUG
QUIET_PATHS = {"/healthz", "/readyz", "/metrics"}
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Запуск и корректная остановка экземпляра.

    По сигналу SIGTERM (docker stop) uvicorn перестаёт принимать новые
    соединения, дожидается завершения текущих запросов и только потом выполняет
    код после yield: соединения с базой закрываются штатно, а не обрываются.
    """
    logger.info("Экземпляр %s запущен", settings.instance_id, extra={"event": "app_started"})
    yield
    engine.dispose()
    logger.info(
        "Экземпляр %s остановлен: соединения с БД закрыты",
        settings.instance_id,
        extra={"event": "app_stopped"},
    )


app = FastAPI(
    title="Складской учёт",
    description=(
        "Учебный проект по курсу «Методология и практики DevOps». "
        "Учёт материалов, единиц измерения, поставщиков и поступлений на склад. "
        "Просмотр данных открыт всем; добавление, изменение и удаление — только после "
        "входа по логину и паролю (кнопка Authorize)."
    ),
    version=__version__,
    openapi_url="/openapi.json",
    docs_url="/docs",
    lifespan=lifespan,
)

register_error_handlers(app)


def endpoint_of(request: Request) -> str:
    """Шаблон маршрута запроса (/api/v1/materials/{material_id}) для журнала и метрик."""
    for route in request.app.routes:
        match, _ = route.matches(request.scope)
        if match == Match.FULL:
            return getattr(route, "path", "unmatched")
    return "unmatched"


def result_of(status: int) -> str:
    if status >= 500:
        return "server_error"
    return "client_error" if status >= 400 else "ok"


@app.middleware("http")
async def observe_request(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Журнал и метрики каждого запроса; идентификаторы запроса и экземпляра в ответе.

    request_id приходит от Nginx (X-Request-ID) или создаётся здесь и попадает
    во все записи журнала, сделанные при обработке запроса.
    """
    incoming = request.headers.get("x-request-id", "")
    request_id = incoming if REQUEST_ID_RE.match(incoming) else uuid.uuid4().hex
    token = request_id_var.set(request_id)
    started = time.perf_counter()
    status = 500
    metrics.HTTP_IN_PROGRESS.inc()
    try:
        response = await call_next(request)
        status = response.status_code
    except Exception:
        logger.exception("Необработанная ошибка", extra={"event": "unhandled_error"})
        raise
    finally:
        seconds = time.perf_counter() - started
        endpoint = endpoint_of(request)
        metrics.HTTP_IN_PROGRESS.dec()
        metrics.observe_request(request.method, endpoint, status, seconds)
        access_logger.log(
            logging.DEBUG if request.url.path in QUIET_PATHS else logging.INFO,
            "%s %s → %s",
            request.method,
            endpoint,
            status,
            extra={
                "event": "http_request",
                "method": request.method,
                "endpoint": endpoint,
                "path": request.url.path,
                "status": status,
                "result": result_of(status),
                "duration_ms": round(seconds * 1000, 2),
                "client": request.client.host if request.client else None,
            },
        )
        request_id_var.reset(token)
    response.headers["X-Instance-Id"] = settings.instance_id
    response.headers["X-Request-ID"] = request_id
    return response


# health-check, метрики и корневой адрес открыты: их опрашивает мониторинг.
app.include_router(health.router)
app.include_router(metrics.router)

# Разграничение прав: читать может любой, добавлять и изменять — только после входа.
protected = [Depends(require_auth_for_changes)]
app.include_router(units.router, dependencies=protected)
app.include_router(suppliers.router, dependencies=protected)
app.include_router(materials.router, dependencies=protected)
app.include_router(receipts.router, dependencies=protected)
app.include_router(reports.router, dependencies=protected)


@app.get("/", tags=["health"], summary="Информация о сервисе")
def root() -> dict[str, str]:
    return {
        "service": settings.app_name,
        "version": __version__,
        "docs": "/docs",
        "health": "/healthz",
        "release": "/version",
    }
