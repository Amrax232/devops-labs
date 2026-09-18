"""Справочник поставщиков."""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app import services
from app.db import get_db
from app.schemas import SupplierCreate, SupplierRead, SupplierUpdate

router = APIRouter(prefix="/api/v1/suppliers", tags=["suppliers"])


@router.get("", response_model=list[SupplierRead], summary="Список поставщиков")
def list_suppliers(
    q: str | None = Query(default=None, description="Поиск по названию или ИНН"),
    only_active: bool = Query(default=False, description="Только активные поставщики"),
    db: Session = Depends(get_db),
) -> list[SupplierRead]:
    return services.list_suppliers(db, query=q, only_active=only_active)


@router.post(
    "",
    response_model=SupplierRead,
    status_code=status.HTTP_201_CREATED,
    summary="Добавить поставщика",
)
def create_supplier(payload: SupplierCreate, db: Session = Depends(get_db)) -> SupplierRead:
    return services.create_supplier(db, payload)


@router.get("/{supplier_id}", response_model=SupplierRead, summary="Карточка поставщика")
def get_supplier(supplier_id: int, db: Session = Depends(get_db)) -> SupplierRead:
    return services.get_supplier(db, supplier_id)


@router.patch("/{supplier_id}", response_model=SupplierRead, summary="Изменить поставщика")
def update_supplier(
    supplier_id: int, payload: SupplierUpdate, db: Session = Depends(get_db)
) -> SupplierRead:
    return services.update_supplier(db, supplier_id, payload)


@router.delete(
    "/{supplier_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить поставщика",
)
def delete_supplier(supplier_id: int, db: Session = Depends(get_db)) -> None:
    services.delete_supplier(db, supplier_id)
