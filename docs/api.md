# Описание API

Базовый адрес: `http://localhost:8000`
Формат обмена: JSON, кодировка UTF-8.
Интерактивная документация (OpenAPI): `/docs`, схема — `/openapi.json`.

## Авторизация

Все эндпоинты данных (`/api/v1/*`) требуют HTTP Basic.

| Заголовок | Формат |
| :--- | :--- |
| `Authorization` | `Basic base64(username:password)` |

Учётные данные — из переменных окружения `AUTH_USERNAME`, `AUTH_PASSWORD`.

Открытыми остаются:

- `GET /` — информация о сервисе;
- `GET /healthz` — liveness (процесс жив);
- `GET /readyz` — readiness (БД доступна).

Пример:

```bash
# без пароля → 401 unauthorized
curl -i localhost:8000/api/v1/materials

# HTTP/1.1 401 Unauthorized
# www-authenticate: Basic realm="warehouse"
# {"error":{"code":"unauthorized","message":"Требуется вход: укажите логин и пароль"}}

# с паролем → 200
curl -u admin:warehouse123 localhost:8000/api/v1/materials
```

В Swagger UI кнопка **Authorize** — справа сверху.

---

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
| 401 | `unauthorized` | нет логина и пароля или они неверны |
| 404 | `not_found` | объект не найден |
| 409 | `conflict` | нарушена уникальность или есть зависимые записи |
| 409 | `integrity_error` | ограничение целостности на уровне БД |
| 422 | `validation_error` | некорректное тело запроса |
| 422 | `business_rule_violated` | запрос запрещён правилами предметной области |

---

## Служебные маршруты

```bash
curl http://localhost:8000/healthz
# {"status":"ok","app":"warehouse-inventory","version":"0.2.0","environment":"local"}

curl http://localhost:8000/readyz
# {"status":"ok","database":"ok"}
```

---

## Единицы измерения

```bash
# создать
curl -u admin:warehouse123 -X POST http://localhost:8000/api/v1/units \
  -H 'Content-Type: application/json' \
  -d '{"code": "kg", "name": "Килограмм"}'
# 201 {"id":1,"code":"kg","name":"Килограмм"}

# список
curl -u admin:warehouse123 http://localhost:8000/api/v1/units

# удалить (409, если единица используется материалами)
curl -u admin:warehouse123 -X DELETE http://localhost:8000/api/v1/units/1
```

---

## Поставщики

```bash
curl -u admin:warehouse123 -X POST http://localhost:8000/api/v1/suppliers \
  -H 'Content-Type: application/json' \
  -d '{"name": "ООО \"Метизы\"", "inn": "7701234567", "email": "sales@metiz.example"}'
# 201 {"id":1,"name":"ООО \"Метизы\"","inn":"7701234567","email":"sales@metiz.example","is_active":true}

# поиск по названию или ИНН (без учёта регистра)
curl -u admin:warehouse123 'http://localhost:8000/api/v1/suppliers?q=Метизы'
curl -u admin:warehouse123 'http://localhost:8000/api/v1/suppliers?q=770123'

# только активные
curl -u admin:warehouse123 'http://localhost:8000/api/v1/suppliers?only_active=true'

# поиск и фильтр сочетаются
curl -u admin:warehouse123 'http://localhost:8000/api/v1/suppliers?q=Метизы&only_active=true'

# деактивировать
curl -u admin:warehouse123 -X PATCH http://localhost:8000/api/v1/suppliers/1 \
  -H 'Content-Type: application/json' -d '{"is_active": false}'

# удалить (409, если есть поступления)
curl -u admin:warehouse123 -X DELETE http://localhost:8000/api/v1/suppliers/1
```

Некорректный ИНН:

```bash
curl -u admin:warehouse123 -X POST http://localhost:8000/api/v1/suppliers \
  -H 'Content-Type: application/json' -d '{"name": "ООО Тест", "inn": "123"}'
# 422 {"error":{"code":"validation_error", ...}}
```

---

## Материалы

```bash
curl -u admin:warehouse123 -X POST http://localhost:8000/api/v1/materials \
  -H 'Content-Type: application/json' \
  -d '{"sku": "MAT-001", "name": "Болт М8х40", "unit_id": 1, "min_stock": "50"}'
# 201 {"id":1,"sku":"MAT-001","name":"Болт М8х40","quantity":"0.000","min_stock":"50.000","unit":{"id":1,"code":"kg","name":"Килограмм"}}

# поиск по названию/артикулу и фильтр «ниже минимума»
curl -u admin:warehouse123 'http://localhost:8000/api/v1/materials?q=болт'
curl -u admin:warehouse123 'http://localhost:8000/api/v1/materials?below_min=true'

# изменить минимальный запас
curl -u admin:warehouse123 -X PATCH http://localhost:8000/api/v1/materials/1 \
  -H 'Content-Type: application/json' -d '{"min_stock": "100"}'
```

Остаток (`quantity`) напрямую не редактируется — он изменяется только
проведением документов поступления.

---

## Поступления

```bash
# создать черновик сразу со строками
curl -u admin:warehouse123 -X POST http://localhost:8000/api/v1/receipts \
  -H 'Content-Type: application/json' \
  -d '{
        "number": "ПН-0001",
        "supplier_id": 1,
        "received_at": "2026-09-01",
        "items": [{"material_id": 1, "quantity": "10.5", "price": "25.50"}]
      }'
# 201 {"id":1,"number":"ПН-0001","status":"draft","items":[...],"total_amount":"267.75"}

# добавить строку в черновик
curl -u admin:warehouse123 -X POST http://localhost:8000/api/v1/receipts/1/items \
  -H 'Content-Type: application/json' -d '{"material_id": 2, "quantity": "3", "price": "40"}'

# удалить строку
curl -u admin:warehouse123 -X DELETE http://localhost:8000/api/v1/receipts/1/items/2

# провести документ: остатки материалов увеличиваются
curl -u admin:warehouse123 -X POST http://localhost:8000/api/v1/receipts/1/post
# 200 {"id":1,"status":"posted","posted_at":"2026-09-10T12:00:00+00:00", ...}

# повторное проведение запрещено
curl -u admin:warehouse123 -X POST http://localhost:8000/api/v1/receipts/1/post
# 422 {"error":{"code":"business_rule_violated","message":"Проведённое поступление изменить нельзя"}}

# фильтры списка
curl -u admin:warehouse123 'http://localhost:8000/api/v1/receipts?status=posted&date_from=2026-09-01&date_to=2026-09-30'
```

---

## Отчёты

```bash
# остатки на складе
curl -u admin:warehouse123 http://localhost:8000/api/v1/reports/stock
# {"rows":[{"material_id":1,"sku":"MAT-001","name":"Болт М8х40","unit_code":"kg",
#           "quantity":"10.500","min_stock":"50.000","below_min":true}],"positions":1}

# только дефицитные позиции
curl -u admin:warehouse123 'http://localhost:8000/api/v1/reports/stock?below_min=true'

# сортировка по имени или количеству
curl -u admin:warehouse123 'http://localhost:8000/api/v1/reports/stock?order_by=name'
curl -u admin:warehouse123 'http://localhost:8000/api/v1/reports/stock?order_by=quantity'

# ограничение числа строк
curl -u admin:warehouse123 'http://localhost:8000/api/v1/reports/stock?limit=5'

# поступления по поставщикам за период (учитываются только проведённые документы)
curl -u admin:warehouse123 'http://localhost:8000/api/v1/reports/receipts?date_from=2026-09-01&date_to=2026-09-30'
# {"date_from":"2026-09-01","date_to":"2026-09-30",
#  "rows":[{"supplier_id":1,"supplier_name":"ООО \"Метизы\"","receipts_count":1,"total_amount":"267.75"}],
#  "total_amount":"267.75"}
```

---

## Сквозной сценарий проверки

```bash
AUTH="-u admin:warehouse123"
BASE="http://localhost:8000/api/v1"

curl $AUTH -X POST $BASE/units -H 'Content-Type: application/json' -d '{"code":"pcs","name":"Штука"}'
curl $AUTH -X POST $BASE/suppliers -H 'Content-Type: application/json' -d '{"name":"ООО Метизы","inn":"7701234567"}'
curl $AUTH -X POST $BASE/materials -H 'Content-Type: application/json' -d '{"sku":"MAT-001","name":"Болт М8х40","unit_id":1,"min_stock":"50"}'
curl $AUTH -X POST $BASE/receipts -H 'Content-Type: application/json' -d '{"number":"ПН-0001","supplier_id":1,"received_at":"2026-09-01","items":[{"material_id":1,"quantity":"100","price":"12.30"}]}'
curl $AUTH -X POST $BASE/receipts/1/post
curl $AUTH $BASE/reports/stock
```