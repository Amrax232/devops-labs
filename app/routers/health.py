"""Служебные маршруты: проверка работоспособности."""

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import __version__
from app.config import Settings, get_settings
from app.db import get_db
from app.schemas import HealthResponse, ReadinessResponse, VersionResponse

router = APIRouter(tags=["health"])


@router.get("/healthz", response_model=HealthResponse, summary="Приложение живо")
def healthz(settings: Settings = Depends(get_settings)) -> HealthResponse:
    return HealthResponse(
        status="ok",
        app=settings.app_name,
        version=__version__,
        environment=settings.app_env,
        instance=settings.instance_id,
    )


@router.get("/version", response_model=VersionResponse, summary="Работающая версия")
def version(settings: Settings = Depends(get_settings)) -> VersionResponse:
    """Версия и коммит образа: проверка после развёртывания сверяет их с выпуском."""
    return VersionResponse(
        version=__version__,
        revision=settings.app_revision,
        environment=settings.app_env,
        instance=settings.instance_id,
    )


@router.get("/readyz", response_model=ReadinessResponse, summary="Приложение готово к работе")
def readyz(response: Response, db: Session = Depends(get_db)) -> ReadinessResponse:
    """Готовность = приложение отвечает и база данных доступна.

    Без базы — 503: healthcheck контейнера и проверка после развёртывания
    считают такой экземпляр неготовым.
    """
    try:
        db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - наружу отдаём только статус
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(status="degraded", database="unavailable")
    return ReadinessResponse(status="ok", database="ok")
