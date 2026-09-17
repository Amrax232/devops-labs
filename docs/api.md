# Описание API

Базовый адрес: `http://localhost:8000`
Формат обмена: JSON, кодировка UTF-8.
Интерактивная документация (OpenAPI): `/docs`, схема — `/openapi.json`.

## Формат ошибок

```json
{
  "error": {
    "code": "business_rule_violated",
    "message": "Проведённое поступление изменить нельзя",
    "details": {"receipt_id": 1, "status": "posted"}
  }
}
```

| HTTP | `code` | Когда |
|---|---|---|
| 404 | `not_found` | объект не найден |
| 409 | `conflict` | нарушена уникальность или есть зависимые записи |
| 409 | `integrity_error` | ограничение целостности на уровне БД |
| 422 | `validation_error` | некорректное тело запроса |
| 422 | `business_rule_violated` | запрос запрещён правилами предметной области |

---

## Служебные маршруты

```bash
curl http://localhost:8000/healthz
# {"status":"ok","app":"warehouse-inventory","version":"0.1.0","environment":"local"}

curl http://localhost:8000/readyz
# {"status":"ok","database":"ok"}
```

---

## Единицы измерения

```bash
# создать
curl -X POST http://localhost:8000/api/v1/units \
  -H 'Content-Type: application/json' \
  -d '{"code": "kg", "name": "Килограмм"}'
# 201 {"id":1,"code":"kg","name":"Килограмм"}

# список
curl http://localhost:8000/api/v1/units

# удалить (409, если единица используется материалами)
curl -X DELETE http://localhost:8000/api/v1/units/1
```

---

## Поставщики

```bash
curl -X POST http://localhost:8000/api/v1/suppliers \
  -H 'Content-Type: application/json' \
  -d '{"name": "ООО \"Метизы\"", "inn": "7701234567", "email": "sales@metiz.example"}'
# 201 {"id":1,"name":"ООО \"Метизы\"","inn":"7701234567","email":"sales@metiz.example","is_active":true}

# поиск по названию или ИНН (без учёта регистра)
curl 'http://localhost:8000/api/v1/suppliers?q=Метизы'
curl 'http://localhost:8000/api/v1/suppliers?q=770123'

# только активные
curl 'http://localhost:8000/api/v1/suppliers?only_active=true'

# поиск и фильтр сочетаются
curl 'http://localhost:8000/api/v1/suppliers?q=Метизы&only_active=true'

# деактивировать
curl -X PATCH http://localhost:8000/api/v1/suppliers/1 \
  -H 'Content-Type: application/json' -d '{"is_active": false}'

# удалить (409, если есть поступления)
curl -X DELETE http://localhost:8000/api/v1/suppliers/1
```

Некорректный ИНН:

```bash
curl -X POST http://localhost:8000/api/v1/suppliers \
  -H 'Content-Type: application/json' -d '{"name": "ООО Тест", "inn": "123"}'
# 422 {"error":{"code":"validation_error", ...}}
```

---

## Материалы

```bash
curl -X POST http://localhost:8000/api/v1/materials \
  -H 'Content-Type: application/json' \
  -d '{"sku": "MAT-001", "name": "Болт М8х40", "unit_id": 1, "min_stock": "50"}'
# 201 {"id":1,"sku":"MAT-001","name":"Болт М8х40","quantity":"0.000","min_stock":"50.000","unit":{"id":1,"code":"kg","name":"Килограмм"}}

# поиск по названию/артикулу и фильтр «ниже минимума»
curl 'http://localhost:8000/api/v1/materials?q=болт'
curl 'http://localhost:8000/api/v1/materials?below_min=true'

# изменить минимальный запас
curl -X PATCH http://localhost:8000/api/v1/materials/1 \
  -H 'Content-Type: application/json' -d '{"min_stock": "100"}'
```

Остаток (`quantity`) напрямую не редактируется — он изменяется только
проведением документов поступления.

---

## Поступления

```bash
# создать черновик сразу со строками
curl -X POST http://localhost:8000/api/v1/receipts \
  -H 'Content-Type: application/json' \
  -d '{
        "number": "ПН-0001",
        "supplier_id": 1,
        "received_at": "2026-09-01",
        "items": [{"material_id": 1, "quantity": "10.5", "price": "25.50"}]
      }'
# 201 {"id":1,"number":"ПН-0001","status":"draft","items":[...],"total_amount":"267.75"}

# добавить строку в черновик
curl -X POST http://localhost:8000/api/v1/receipts/1/items \
  -H 'Content-Type: application/json' -d '{"material_id": 2, "quantity": "3", "price": "40"}'

# удалить строку
curl -X DELETE http://localhost:8000/api/v1/receipts/1/items/2

# провести документ: остатки материалов увеличиваются
curl -X POST http://localhost:8000/api/v1/receipts/1/post
# 200 {"id":1,"status":"posted","posted_at":"2026-09-10T12:00:00+00:00", ...}

# повторное проведение запрещено
curl -X POST http://localhost:8000/api/v1/receipts/1/post
# 422 {"error":{"code":"business_rule_violated","message":"Проведённое поступление изменить нельзя"}}

# фильтры списка
curl 'http://localhost:8000/api/v1/receipts?status=posted&date_from=2026-09-01&date_to=2026-09-30'
```

---

## Отчёты

```bash
# остатки на складе
curl http://localhost:8000/api/v1/reports/stock
# {"rows":[{"material_id":1,"sku":"MAT-001","name":"Болт М8х40","unit_code":"kg",
#           "quantity":"10.500","min_stock":"50.000","below_min":true}],"positions":1}

# только дефицитные позиции
curl 'http://localhost:8000/api/v1/reports/stock?below_min=true'

# поступления по поставщикам за период (учитываются только проведённые документы)
curl 'http://localhost:8000/api/v1/reports/receipts?date_from=2026-09-01&date_to=2026-09-30'
# {"date_from":"2026-09-01","date_to":"2026-09-30",
#  "rows":[{"supplier_id":1,"supplier_name":"ООО \"Метизы\"","receipts_count":1,"total_amount":"267.75"}],
#  "total_amount":"267.75"}
```

---

## Сквозной сценарий проверки

```bash
curl -X POST localhost:8000/api/v1/units -H 'Content-Type: application/json' -d '{"code":"pcs","name":"Штука"}'
curl -X POST localhost:8000/api/v1/suppliers -H 'Content-Type: application/json' -d '{"name":"ООО Метизы","inn":"7701234567"}'
curl -X POST localhost:8000/api/v1/materials -H 'Content-Type: application/json' -d '{"sku":"MAT-001","name":"Болт М8х40","unit_id":1,"min_stock":"50"}'
curl -X POST localhost:8000/api/v1/receipts -H 'Content-Type: application/json' -d '{"number":"ПН-0001","supplier_id":1,"received_at":"2026-09-01","items":[{"material_id":1,"quantity":"100","price":"12.30"}]}'
curl -X POST localhost:8000/api/v1/receipts/1/post
curl localhost:8000/api/v1/reports/stock
```
