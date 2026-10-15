"""Справочник материалов и текущие остатки."""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app import services
from app.db import get_db
from app.schemas import (
    MaterialCreate,
    MaterialRead,
    MaterialUpdate,
    WriteOffCreate,
    WriteOffRead,
)

router = APIRouter(prefix="/api/v1/materials", tags=["materials"])


@router.get("", response_model=list[MaterialRead], summary="Список материалов")
def list_materials(
    q: str | None = Query(default=None, description="Поиск по названию или артикулу"),
    below_min: bool = Query(default=False, description="Только позиции ниже минимума"),
    db: Session = Depends(get_db),
) -> list[MaterialRead]:
    return services.list_materials(db, query=q, below_min=below_min)


@router.post(
    "",
    response_model=MaterialRead,
    status_code=status.HTTP_201_CREATED,
    summary="Добавить материал",
)
def create_material(payload: MaterialCreate, db: Session = Depends(get_db)) -> MaterialRead:
    return services.create_material(db, payload)


@router.get("/{material_id}", response_model=MaterialRead, summary="Карточка материала")
def get_material(material_id: int, db: Session = Depends(get_db)) -> MaterialRead:
    return services.get_material(db, material_id)


@router.patch("/{material_id}", response_model=MaterialRead, summary="Изменить материал")
def update_material(
    material_id: int, payload: MaterialUpdate, db: Session = Depends(get_db)
) -> MaterialRead:
    return services.update_material(db, material_id, payload)


@router.delete(
    "/{material_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить материал",
)
def delete_material(material_id: int, db: Session = Depends(get_db)) -> None:
    services.delete_material(db, material_id)


@router.post(
    "/{material_id}/write-offs",
    response_model=WriteOffRead,
    status_code=status.HTTP_201_CREATED,
    summary="Списать материал",
)
def create_write_off(
    material_id: int, payload: WriteOffCreate, db: Session = Depends(get_db)
) -> WriteOffRead:
    """Уменьшает остаток. Списать больше, чем есть на складе, нельзя."""
    return services.create_write_off(db, material_id, payload)


@router.get(
    "/{material_id}/write-offs",
    response_model=list[WriteOffRead],
    summary="История списаний материала",
)
def list_write_offs(material_id: int, db: Session = Depends(get_db)) -> list[WriteOffRead]:
    return services.list_write_offs(db, material_id)
