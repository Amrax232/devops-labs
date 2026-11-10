"""Метрики приложения в формате Prometheus (ЛР8): GET /metrics.

  - запросы: warehouse_http_requests_total{method, endpoint, status};
  - ошибки: те же счётчики со status 4xx/5xx (доля ошибок считается в Prometheus);
  - время ответа: warehouse_http_request_duration_seconds (гистограмма);
  - состояние: warehouse_app_info, warehouse_database_up, запросы в обработке;
  - предметные: warehouse_materials_below_min — позиций ниже минимального
    остатка, warehouse_materials_total, warehouse_stock_operations_total{operation}
    — проведённые поступления и списания;
  - безопасность: warehouse_log_secrets_redacted_total, warehouse_auth_failures_total.

endpoint — шаблон маршрута (/api/v1/materials/{material_id}), а не конкретный
адрес: число рядов метрики не растёт с числом объектов.

Адрес /metrics наружу не публикуется: Nginx отвечает на него 404, метрики
собирает Prometheus во внутренней сети.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

from fastapi import APIRouter, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector
from sqlalchemy import func, select, text

logger = logging.getLogger(__name__)

HTTP_REQUESTS = Counter(
    "warehouse_http_requests_total",
    "HTTP-запросы по методу, адресу операции и коду ответа",
    ["method", "endpoint", "status"],
)
HTTP_DURATION = Histogram(
    "warehouse_http_request_duration_seconds",
    "Время ответа на HTTP-запрос",
    ["method", "endpoint"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
HTTP_IN_PROGRESS = Gauge("warehouse_http_requests_in_progress", "Запросы в обработке")
APP_INFO = Gauge(
    "warehouse_app_info",
    "Работающая версия экземпляра (значение всегда 1)",
    ["version", "revision", "instance", "environment"],
)
STOCK_OPERATIONS = Counter(
    "warehouse_stock_operations_total",
    "Складские операции: проведённые поступления и списания",
    ["operation"],
)
SECRETS_REDACTED = Counter(
    "warehouse_log_secrets_redacted_total",
    "Секреты, замаскированные при записи в журнал (их появление — ошибка в коде)",
)
AUTH_FAILURES = Counter(
    "warehouse_auth_failures_total",
    "Запросы, отклонённые из-за отсутствия или неверных логина и пароля",
)

# ряды предметной метрики видны сразу, даже до первой операции
for _operation in ("receipt_posted", "write_off"):
    STOCK_OPERATIONS.labels(_operation)


def observe_request(method: str, endpoint: str, status: int, seconds: float) -> None:
    HTTP_REQUESTS.labels(method, endpoint, str(status)).inc()
    HTTP_DURATION.labels(method, endpoint).observe(seconds)


class DatabaseCollector(Collector):
    """Значения, которые читаются из базы в момент сбора метрик Prometheus."""

    def collect(self) -> Iterator[GaugeMetricFamily]:
        from app.db import SessionLocal
        from app.models import Material

        up = GaugeMetricFamily("warehouse_database_up", "База данных доступна (1) или нет (0)")
        try:
            with SessionLocal() as db:
                db.execute(text("SELECT 1"))
                below = db.scalar(
                    select(func.count())
                    .select_from(Material)
                    .where(Material.quantity < Material.min_stock)
                )
                total = db.scalar(select(func.count()).select_from(Material))
        except Exception:  # noqa: BLE001 - недоступность базы — это значение метрики, а не сбой
            logger.warning(
                "База данных недоступна при сборе метрик", extra={"event": "db_unavailable"}
            )
            up.add_metric([], 0)
            yield up
            return
        up.add_metric([], 1)
        yield up
        yield GaugeMetricFamily(
            "warehouse_materials_below_min",
            "Материалы, остаток которых ниже минимального (нужна закупка)",
            value=below or 0,
        )
        yield GaugeMetricFamily(
            "warehouse_materials_total", "Материалы в справочнике", value=total or 0
        )


REGISTRY.register(DatabaseCollector())

router = APIRouter(tags=["health"])


@router.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    """Метрики для Prometheus (во внутренней сети; через Nginx недоступны)."""
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
