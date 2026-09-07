"""Точка входа приложения «Складской учёт»."""

import logging

from fastapi import FastAPI

from app import __version__
from app.config import get_settings
from app.errors import register_error_handlers
from app.routers import health, units, suppliers, materials, receipts, reports

settings = get_settings()
logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

app = FastAPI(
    title="Складской учёт",
    description=(
        "Учебный проект по курсу «Методология и практики DevOps». "
        "Учёт материалов, единиц измерения, поставщиков и поступлений на склад."
    ),
    version=__version__,
    openapi_url="/openapi.json",
    docs_url="/docs",
)

register_error_handlers(app)

app.include_router(health.router)
app.include_router(units.router)
app.include_router(suppliers.router)
app.include_router(materials.router)
app.include_router(receipts.router)
app.include_router(reports.router)


@app.get("/", tags=["health"], summary="Информация о сервисе")
def root() -> dict[str, str]:
    return {
        "service": settings.app_name,
        "version": __version__,
        "docs": "/docs",
        "health": "/healthz",
    }
