"""Служебные маршруты: проверка работоспособности."""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import __version__
from app.config import Settings, get_settings
from app.db import get_db
from app.schemas import HealthResponse, ReadinessResponse

router = APIRouter(tags=["health"])


@router.get("/healthz", response_model=HealthResponse, summary="Приложение живо")
def healthz(settings: Settings = Depends(get_settings)) -> HealthResponse:
    return HealthResponse(
        status="ok",
        app=settings.app_name,
        version=__version__,
        environment=settings.app_env,
    )


@router.get("/readyz", response_model=ReadinessResponse, summary="Приложение готово к работе")
def readyz(db: Session = Depends(get_db)) -> ReadinessResponse:
    """Готовность = приложение отвечает и база данных доступна."""
    try:
        db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - наружу отдаём только статус
        return ReadinessResponse(status="degraded", database="unavailable")
    return ReadinessResponse(status="ok", database="ok")
