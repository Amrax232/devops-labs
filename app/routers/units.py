"""Справочник единиц измерения."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app import services
from app.db import get_db
from app.schemas import UnitCreate, UnitRead

router = APIRouter(prefix="/api/v1/units", tags=["units"])


@router.get("", response_model=list[UnitRead], summary="Список единиц измерения")
def list_units(db: Session = Depends(get_db)) -> list[UnitRead]:
    return services.list_units(db)


@router.post(
    "",
    response_model=UnitRead,
    status_code=status.HTTP_201_CREATED,
    summary="Создать единицу измерения",
)
def create_unit(payload: UnitCreate, db: Session = Depends(get_db)) -> UnitRead:
    return services.create_unit(db, payload)


@router.delete(
    "/{unit_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить единицу измерения",
)
def delete_unit(unit_id: int, db: Session = Depends(get_db)) -> None:
    services.delete_unit(db, unit_id)
