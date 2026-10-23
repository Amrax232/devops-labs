"""Точка входа приложения «Складской учёт»."""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request, Response

from app import __version__
from app.config import get_settings
from app.db import engine
from app.errors import register_error_handlers
from app.routers import health, materials, receipts, reports, suppliers, units
from app.security import require_auth_for_changes

settings = get_settings()
logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Запуск и корректная остановка экземпляра.

    По сигналу SIGTERM (docker stop) uvicorn перестаёт принимать новые
    соединения, дожидается завершения текущих запросов и только потом выполняет
    код после yield: соединения с базой закрываются штатно, а не обрываются.
    """
    logger.info("Экземпляр %s запущен", settings.instance_id)
    yield
    engine.dispose()
    logger.info("Экземпляр %s остановлен: соединения с БД закрыты", settings.instance_id)


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


@app.middleware("http")
async def add_instance_header(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Каждый ответ сообщает, какой экземпляр приложения его сформировал."""
    response = await call_next(request)
    response.headers["X-Instance-Id"] = settings.instance_id
    return response


# health-check и корневой адрес открыты: их опрашивает мониторинг.
app.include_router(health.router)

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
    }
