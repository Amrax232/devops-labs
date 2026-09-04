"""Поступления материалов на склад."""

from datetime import date

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app import services
from app.db import get_db
from app.models import ReceiptStatus
from app.schemas import ReceiptCreate, ReceiptItemCreate, ReceiptRead

router = APIRouter(prefix="/api/v1/receipts", tags=["receipts"])


@router.get("", response_model=list[ReceiptRead], summary="Список поступлений")
def list_receipts(
    supplier_id: int | None = Query(default=None),
    receipt_status: ReceiptStatus | None = Query(default=None, alias="status"),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[ReceiptRead]:
    return services.list_receipts(
        db,
        supplier_id=supplier_id,
        status=receipt_status,
        date_from=date_from,
        date_to=date_to,
    )


@router.post(
    "",
    response_model=ReceiptRead,
    status_code=status.HTTP_201_CREATED,
    summary="Создать поступление (черновик)",
)
def create_receipt(payload: ReceiptCreate, db: Session = Depends(get_db)) -> ReceiptRead:
    return services.create_receipt(db, payload)


@router.get("/{receipt_id}", response_model=ReceiptRead, summary="Карточка поступления")
def get_receipt(receipt_id: int, db: Session = Depends(get_db)) -> ReceiptRead:
    return services.get_receipt(db, receipt_id)


@router.post(
    "/{receipt_id}/items",
    response_model=ReceiptRead,
    status_code=status.HTTP_201_CREATED,
    summary="Добавить строку в черновик",
)
def add_item(
    receipt_id: int, payload: ReceiptItemCreate, db: Session = Depends(get_db)
) -> ReceiptRead:
    return services.add_receipt_item(db, receipt_id, payload)


@router.delete(
    "/{receipt_id}/items/{item_id}",
    response_model=ReceiptRead,
    summary="Удалить строку из черновика",
)
def delete_item(receipt_id: int, item_id: int, db: Session = Depends(get_db)) -> ReceiptRead:
    return services.delete_receipt_item(db, receipt_id, item_id)


@router.post(
    "/{receipt_id}/post",
    response_model=ReceiptRead,
    summary="Провести поступление (увеличить остатки)",
)
def post_receipt(receipt_id: int, db: Session = Depends(get_db)) -> ReceiptRead:
    return services.post_receipt(db, receipt_id)


@router.delete(
    "/{receipt_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить черновик поступления",
)
def delete_receipt(receipt_id: int, db: Session = Depends(get_db)) -> None:
    services.delete_receipt(db, receipt_id)
