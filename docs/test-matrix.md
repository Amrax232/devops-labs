# Матрица трассировки: требования ТЗ → тесты

Требование работы — тесты покрывают не менее 40 % функционала, описанного в
ТЗ ([`tz.md`](tz.md)). Покрытие считается по пунктам ТЗ, а не по строкам кода:
пункт покрыт, если есть хотя бы один автоматический тест, который упадёт при
нарушении этого пункта.

Уровни: **U** — unit (`tests/unit`), **A** — HTTP API на SQLite (`tests/api`),
**I** — интеграционные на PostgreSQL (`tests/integration`).

## Функции

| Пункт | Функция | Уровни | Тесты |
|---|---|---|---|
| Ф1 | Ведение единиц измерения | A | `test_unit_code_is_unique`, `test_unit_in_use_cannot_be_deleted` |
| Ф2 | Ведение поставщиков | A, I | `test_supplier_inn_is_unique`, `test_supplier_can_be_deactivated`, `test_supplier_phone_boundaries`, `test_full_flow_on_postgresql` |
| Ф3 | Ведение материалов | A | `test_material_sku_is_unique`, `test_material_requires_existing_unit`, `test_new_material_has_zero_quantity`, `test_material_location_can_be_changed` |
| Ф4 | Поиск материалов | A | `test_material_search_by_name_and_sku` |
| Ф5 | Регистрация поступления | A | `test_receipt_is_created_as_draft`, `test_receipt_number_is_unique`, `test_receipt_requires_existing_supplier` |
| Ф6 | Редактирование строк черновика | A | `test_draft_can_be_edited_and_deleted` |
| Ф7 | Проведение поступления | U, A, I | `test_receipt_increases_stock`, `test_posting_increases_material_quantity`, `test_full_flow_on_postgresql` |
| Ф8 | Отчёт по остаткам | U, A | `test_is_below_min`, `test_stock_report_marks_positions_below_minimum` |
| Ф9 | Отчёт по поступлениям | A, I | `test_receipts_report_counts_only_posted_documents`, `test_receipts_report_respects_period`, `test_full_flow_on_postgresql` |
| Ф10 | Проверка работоспособности | A, I | `test_healthz`, `test_readyz_reports_database`, `test_full_flow_on_postgresql` |
| Ф11 | Поиск поставщиков | A | `test_supplier_search_by_name_and_inn` |
| Ф12 | Сортировка и ограничение отчёта | A | `test_stock_report_can_be_sorted`, `test_stock_report_respects_limit`, `test_stock_report_limit_boundaries` |
| Ф13 | Списание материала | U, A, I | `test_write_off_decreases_stock` (U и A), `test_whole_stock_can_be_written_off`, `test_concurrent_write_offs_do_not_overdraw_stock` |
| Ф14 | История списаний | A | `test_write_off_history_is_newest_first` |
| Ф15 | Доступ по логину и паролю | A | `test_data_requires_credentials`, `test_wrong_password_is_rejected`, `test_write_off_requires_credentials` |

## Ограничения и правила

| Пункт | Правило | Уровни | Тесты |
|---|---|---|---|
| П1 | Количество строго больше нуля | U, A, I | `test_non_positive_quantity_is_rejected`, `test_receipt_quantity_boundaries`, `test_database_rejects_non_positive_write_off` |
| П2 | Цена не отрицательная | A | `test_receipt_price_boundaries` |
| П3 | Остаток не отрицательный | U, I | `test_write_off_over_stock_is_rejected`, `test_database_rejects_negative_stock` |
| П4 | Один материал — одна строка документа | U, A | `test_duplicate_material_is_rejected`, `test_material_cannot_repeat_in_one_receipt` |
| П5 | Повторное проведение запрещено | U, A, I | `test_posted_receipt_cannot_be_posted_again`, `test_posted_receipt_cannot_be_posted_twice`, `test_full_flow_on_postgresql` |
| П6 | Проведённый документ неизменяем | U, A | `test_posted_receipt_cannot_be_edited`, `test_posted_receipt_is_read_only` |
| П7 | Документ без строк не проводится | U, A | `test_empty_draft_cannot_be_posted`, `test_empty_receipt_cannot_be_posted` |
| П8 | Нет поступлений от неактивного поставщика | A | `test_inactive_supplier_cannot_receive_goods` |
| П9 | Объект со ссылками не удаляется | A, I | `test_supplier_with_receipts_cannot_be_deleted`, `test_unit_in_use_cannot_be_deleted`, `test_deleting_receipt_removes_its_items` |
| П10 | ИНН — 10 или 12 цифр, уникален | U, A | `test_inn_validation`, `test_supplier_inn_boundaries`, `test_supplier_inn_is_unique` |
| П11 | Уникальность кодов, артикулов, номеров | A, I | `test_unit_code_is_unique`, `test_material_sku_is_unique`, `test_receipt_number_is_unique`, `test_database_rejects_duplicate_sku` |
| П12 | Списать не больше остатка | U, A, I | `test_write_off_over_stock_is_rejected`, `test_cannot_write_off_more_than_stock`, `test_concurrent_write_offs_do_not_overdraw_stock` |
| П13 | Точность количества и цены | A | `test_receipt_quantity_boundaries`, `test_material_min_stock_boundaries` |
| П14 | Материал с движением не удаляется | A | `test_material_with_receipts_cannot_be_deleted`, `test_material_with_write_offs_cannot_be_deleted` |
| П15 | Данные закрыты логином и паролем | A | `test_write_operations_are_protected`, `test_health_stays_public` |

## Итог

| | Всего пунктов | Покрыто тестами | Доля |
|---|---|---|---|
| Функции (Ф1–Ф15) | 15 | 15 | 100 % |
| Правила и ограничения (П1–П15) | 15 | 15 | 100 % |
| **Всего** | **30** | **30** | **100 %** (требуется не менее 40 %) |

Помимо покрытия по пунктам ТЗ контролируются ещё две метрики:

- **покрытие кода** (строки и ветвления пакета `app`) — порог 80 %, отчёт
  `reports/coverage-html/index.html`;
- **оценка мутационного тестирования** правил `app/domain.py` — порог 80 %,
  отчёт `reports/mutation.txt`. Покрытие показывает, что строка выполнилась,
  мутации — что тест действительно заметит её неправильную работу.

Таблицу обновляют в том же merge request, в котором появляется новая функция:
пункт ТЗ без теста — повод вернуть изменение на доработку.
