# Лабораторная работа №8 — что сделано и что показывать на защите

Результат: **по журналам, метрикам и оповещениям можно найти проблему,
определить компонент, подтвердить причину и восстановить работу; изменение
проходит весь процесс от задачи до проверки выпуска.** Подробности —
[`observability.md`](observability.md), действия при сбоях —
[`runbook.md`](runbook.md).

## Соответствие заданию

| № | Требование | Где реализовано |
|---|---|---|
| 1 | Структурированные журналы | JSON, одна строка на событие: `app/logging_setup.py`; Nginx — `log_format json_log` |
| 2 | Время, уровень, тип события, операция, результат, идентификатор запроса | поля `time`, `level`, `event`, `method`+`endpoint`, `status`+`result`, `request_id` (общий для Nginx и приложения) |
| 3 | Секреты не попадают в журналы | маскирование каждой записи + счётчик и оповещение; `make logs-secrets`; тесты `tests/unit/test_logging.py` |
| 4 | Метрики: запросы, ошибки, время ответа, состояние, предметная | `app/metrics.py`: `warehouse_http_requests_total`, гистограмма времени, `warehouse_database_up`, `warehouse_app_info`, `warehouse_materials_below_min`, `warehouse_stock_operations_total` |
| 5 | Сбор метрик и панель | Prometheus, Grafana (`docker-compose.yml`, `monitoring/`) |
| 6 | Метрики инфраструктуры | node-exporter (хост), cAdvisor (контейнеры), blackbox (доступность) |
| 7 | Панель: доступность, нагрузка, ошибки, время ответа, ресурсы, предметная | «Складской учёт — обзор», 4 раздела; состав проверяет `make monitoring-lint` |
| 8 | Правило оповещения | 12 правил с unit-тестами (`monitoring/prometheus/rules`, `tests`) |
| 9 | Инструкция по диагностике и восстановлению | `docs/runbook.md`: порядок, таблица «признак → компонент», 12 разделов |
| 10 | Конфигурация наблюдаемости в репозитории | `monitoring/`, `nginx/nginx.conf`, `docker-compose.yml`; проверка — `make monitoring-lint` в `make verify` и CI |
| 11 | Итоговое изменение через весь процесс | отчёт по списаниям за период (патчи `lab8-e2e`), ниже — шаги |
| 12 | Состояние до и после выпуска | `make release-snapshot NAME=before/after` (`scripts/obs.sh snapshot`) |
| 13–14 | Неизвестный сбой: найти, определить компонент, подтвердить, восстановить | `make status` → оповещение → раздел `runbook.md` → метрика + журнал → восстановление |
| 15 | Улучшение процесса после инцидента | шаблон `docs/incidents/TEMPLATE.md`, варианты улучшений — таблица ниже |
| 16 | Автоматические и организационные барьеры | `observability.md`, раздел 8 |

## Подготовка (один раз)

```bash
git switch -c feature/17-observability          # от main после ЛР7
git am ~/lab8-observability/patches/lab8/*.patch

sudo apt-get install -y jq                      # разбор JSON в сценариях диагностики

# пароль Grafana в локальный .env (файл не в git)
printf '\n# Наблюдаемость (ЛР8)\nGRAFANA_ADMIN_PASSWORD=%s\nGRAFANA_ROOT_URL=http://127.0.0.1:8080/grafana/\n' \
    "$(openssl rand -hex 12)" >> .env

make setup && make lock                         # новая зависимость prometheus-client
./scripts/setup_monitoring_owners.sh            # владельцы monitoring/ в CODEOWNERS
make vault-upgrade ENV=staging                  # пароль Grafana в секреты окружений
make vault-upgrade ENV=production

make verify                                     # 11 шагов, 8-й — monitoring-lint
make up && make container-check                 # 15 шагов, 15-й — наблюдаемость
git add requirements.lock .github/CODEOWNERS infra/inventories/*/group_vars/*/vault.yml
git commit -m "chore: зависимости, владельцы мониторинга, пароль Grafana в vault"
```

Перед слиянием в `main` (после него CD разворачивает 0.11.0 в staging,
а `deploy.sh` требует `GRAFANA_ADMIN_PASSWORD`):

```bash
make infra-apply ENV=staging       # в stage.env появятся GRAFANA_*; работающий выпуск не меняется
git push -u origin feature/17-observability     # → MR → CI → слияние → CD staging
make infra-verify ENV=staging      # в т. ч. Grafana через Nginx и все цели сбора up
make infra-apply ENV=production TAG=sha-<7 знаков коммита>
```

## Что показывать на защите

**1. Структурированные журналы и сквозной запрос**

```bash
curl -si http://127.0.0.1:8080/api/v1/materials | grep -i x-request-id
make logs-find ID=<значение>                   # строка Nginx и строка экземпляра
docker logs --tail 2 warehouse-inventory-app1-1  # исходные JSON-записи
make chaos SCENARIO=auth ARG=3                 # 3 запроса с неверным паролем → 401
make logs-find EVENT=auth_failed SINCE=5m
```

**2. Секреты не попадают в журнал**

```bash
.venv/bin/pytest tests/unit/test_logging.py -v    # пароль → ***, счётчик растёт
make logs-secrets                                 # настоящих паролей в журналах нет
make chaos SCENARIO=secret && make logs-secrets   # строка в обход журнала найдена
```

**3–7. Метрики и панель** — `make grafana`, вход, панель «Складской учёт —
обзор»: доступность, нагрузка, ошибки, время ответа, ресурсы, предметная
метрика. Для живых графиков — `make chaos SCENARIO=traffic ARG=600` в
отдельном терминале. Снаружи метрик нет: `curl -i http://127.0.0.1:8080/metrics` → 404.

```bash
make metrics-query Q='warehouse_materials_below_min'
make metrics-query Q='sum by (status) (rate(warehouse_http_requests_total[5m]))'
```

**8. Оповещение** — `make chaos SCENARIO=db-stop`, через 30–60 с
`make alerts`: `DatabaseUnavailable`, `WarehouseNotReady` и ссылка на раздел
инструкции; в Grafana — таблица «Сработавшие оповещения»;
`make chaos SCENARIO=recover`.

**9–10. Инструкция и конфигурация в репозитории** — `docs/runbook.md`;
`ls -R monitoring`; `make monitoring-lint`. Что ловит проверка — изменить
имя метрики в правиле (`warehouse_database_up` → `warehouse_db_up`) и
запустить снова: «метрики warehouse_db_up нет в app/metrics.py»; вернуть.

**11–12. Итоговое изменение через весь процесс** — отчёт по списаниям за
период (`GET /api/v1/reports/write-offs?date_from=&date_to=`):

1. задача в GitHub Issues «Отчёт по списаниям за период»;
2. ветка `feature/18-write-off-report` от `main`, патчи `lab8-e2e`
   (`git am ~/lab8-observability/patches/lab8-e2e/*.patch`);
3. локально: `make verify`, `make up && make container-check`;
4. состояние до выпуска на staging:
   ```bash
   ssh deployer@192.168.56.20
   cd /opt/warehouse-stage/current && sudo -u deploy PROJECT=warehouse-stage \
       URL=http://192.168.56.20:8080 REPORTS_DIR=/opt/warehouse-stage/state/snapshots \
       ./scripts/obs.sh snapshot before
   ```
5. `git push`, merge request с выводом проверок, CI зелёный, одобрение
   владельца, слияние;
6. CI на `main` публикует образ, CD разворачивает его в staging и
   проверяет;
7. состояние после выпуска — та же команда с `snapshot after`;
   сравнение `diff` двух файлов (`/opt/warehouse-stage/state/snapshots/`):
   новая версия и коммит, оповещений нет, ошибок нет;
8. проверка нового отчёта:
   `curl -s 'http://192.168.56.20:8080/api/v1/reports/write-offs?date_from=2026-11-01' | jq`;
9. production — `make infra-apply ENV=production TAG=sha-<коммит>`.

**13–15. Неизвестный сбой** — его создаёт преподаватель или напарник.
Порядок: `make status` (на сервере — `scripts/obs.sh status`) → оповещение
и раздел инструкции → компонент → причина двумя источниками (метрика и
журнал) → восстановление → `make smoke` → разбор в
`docs/incidents/<дата>-<кратко>.md` и улучшение процесса через MR.

**16. Барьеры** — `observability.md`, раздел 8.

## Сбои, которые могут предложить, и как их найти

| Сбой | Что видно | Подтверждение: метрика + журнал | Восстановление | Возможное улучшение |
|---|---|---|---|---|
| Остановлена БД | `DatabaseUnavailable`, `/readyz` 503, 5xx на API | `warehouse_database_up`=0; `EVENT=db_unavailable`, `docker inspect …-db-1` | `docker start …-db-1` | тест правила для частичной недоступности; шаг в `runbook.md` |
| Неверная конфигурация | экземпляр unhealthy, `WarehouseNotReady` для него | `up`/`probe_success` по экземпляру; ошибка подключения в журнале старта | `make infra-apply` / `.env` + `docker compose up -d` | проверка формата `DATABASE_URL` в `deploy.sh`/роли `warehouse` (assert) |
| Мало места на диске | `DiskSpaceLow` | `node_filesystem_avail_bytes`; ошибки записи в `docker logs …-db-1` | освободить место (`runbook.md`, раздел 3) | `deploy.sh` не начинает выпуск при свободном месте < 10% |
| Перезапуск контейнера | `ContainerRestarted`, `WarehouseInstanceDown` | `container_start_time_seconds`, `RestartCount`; `app_started` в журнале | причина по `ExitCode`/`OOMKilled` | оповещение о частых перезапусках (больше 3 за 15 мин) |
| Превышение лимита памяти | `ContainerMemoryNearLimit`, затем перезапуск | память в % лимита, `container_oom_events_total`; `OOMKilled=true` | перезапуск экземпляра, лимит через MR | тест правила OOM-событий; лимит в `check_containers.py` |
| Ошибка новой версии | `HighErrorRate` после выпуска | 5xx по `endpoint`; `CODE=5`, `unhandled_error` со стеком | `deploy.sh rollback` | тест на ошибку + проверка операции в `smoke_test.sh` |
| Нарушение прав доступа | `AuthFailuresBurst` / права файлов | `warehouse_auth_failures_total`; `EVENT=auth_failed`; `stat` файла настроек | `make infra-apply` | проверка прав в роли `verify` / новое правило nftables |
| Порт недоступен | `WarehouseUnavailable`, соединение отклонено | `probe_success`=0 при работающих экземплярах; `ss -ltn`, `nft list` | `make infra-apply` | проверка порта в `smoke_test.sh` с хоста |
| Не проходит healthcheck | unhealthy, `WarehouseNotReady` | `docker inspect … .State.Health.Log`; журнал экземпляра | устранить причину, `docker restart` | вывод журнала healthcheck в `compose_wait.sh` |
| Секрет в журнале | `SecretRedactedInLogs` / `make logs-secrets` | счётчик `warehouse_log_secrets_redacted_total`; `TEXT='***'` | исправить код; если открыто — сменить секрет | шаблон маскирования + тест; запрет `print()` в `app/` (ruff `T20`) |

Тренировка до защиты — те же сбои на локальном окружении:
`make chaos SCENARIO=<db-stop|config|restart|memory|oom|hang|port|auth|secret>`,
после каждого — `make chaos SCENARIO=recover`. Сценарий `disk` — только на
ВМ: `CONFIRM=1 PROJECT=warehouse-stage ./scripts/chaos.sh disk`.

## Возможные вопросы

- **Почему не Loki/ELK?** Два экземпляра на одной машине: журналы JSON в
  `docker logs` с ротацией и поиск `scripts/logs.sh` по полям дают тот же
  результат без ещё трёх сервисов. При росте числа машин — Loki с тем же
  форматом записей.
- **Чем метрика отличается от журнала?** Метрика — число во времени
  (сколько, как быстро, сколько ошибок): видно, *что* и *когда*. Журнал —
  отдельное событие с подробностями: видно, *почему*. Причина подтверждена,
  когда они согласуются.
- **Зачем `for` в правилах?** Чтобы единичный сбой проверки (перезапуск,
  сеть) не будил дежурного: условие должно держаться 30 с – 5 мин.
- **Почему доля ошибок только по 5xx?** 4xx — ошибка ввода клиента, сервис
  работает правильно; это проверено тестом правила.
- **Почему cAdvisor от root?** Ему нужны cgroups и сведения Docker;
  компенсация — только чтение, без портов, внутренняя сеть, без меток и
  переменных контейнеров в метриках.
- **Как проверить, что оповещение вообще сработает?** Unit-тест правила
  (`promtool test rules`) и `check_monitoring.py`: у каждого правила есть
  тест, где оно срабатывает, а метрика объявлена в коде.
