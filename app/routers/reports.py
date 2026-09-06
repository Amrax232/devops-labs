"""Отчёты по складу."""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import services
from app.db import get_db
from app.schemas import ReceiptsReport, StockReport

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])


@router.get("/stock", response_model=StockReport, summary="Остатки на складе")
def stock(
    below_min: bool = Query(default=False, description="Только позиции ниже минимума"),
    db: Session = Depends(get_db),
) -> StockReport:
    return services.stock_report(db, only_below_min=below_min)


@router.get("/receipts", response_model=ReceiptsReport, summary="Поступления по поставщикам")
def receipts(
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    db: Session = Depends(get_db),
) -> ReceiptsReport:
    return services.receipts_report(db, date_from=date_from, date_to=date_to)
