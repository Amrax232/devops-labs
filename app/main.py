"""Точка входа приложения «Складской учёт»."""

import logging

from fastapi import Depends, FastAPI

from app import __version__
from app.config import get_settings
from app.errors import register_error_handlers
from app.routers import health, materials, receipts, reports, suppliers, units
from app.security import require_auth

settings = get_settings()
logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

app = FastAPI(
    title="Складской учёт",
    description=(
        "Учебный проект по курсу «Методология и практики DevOps». "
        "Учёт материалов, единиц измерения, поставщиков и поступлений на склад. "
        "Доступ к данным — по логину и паролю (кнопка Authorize)."
    ),
    version=__version__,
    openapi_url="/openapi.json",
    docs_url="/docs",
)

register_error_handlers(app)

# health-check и корневой адрес открыты: их опрашивает мониторинг.
app.include_router(health.router)

# Все данные доступны только после ввода логина и пароля.
protected = [Depends(require_auth)]
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