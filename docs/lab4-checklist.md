# Лабораторная работа №4 — что сделано и что показывать на защите

Цель: приложение и база данных работают в контейнерах. Окружение
воспроизводимо, проверяется автоматически и проходит `make container-check`.
Подробное описание — [`containers.md`](containers.md).

## Основные задания

| № | Требование | Где реализовано |
|---|---|---|
| 1 | Dockerfile и .dockerignore | `Dockerfile` (двухэтапная сборка), `.dockerignore` (белый список) |
| 2 | Воспроизводимая сборка | базовые образы с точными версиями; зависимости по `requirements.lock`; контекст сборки — белый список |
| 3 | Непривилегированный пользователь | `USER 10001:10001` в образе, `user:` в compose; nginx-unprivileged (uid 101); PostgreSQL понижает права до `postgres` |
| 4 | Настройки через переменные окружения | `Settings` (pydantic-settings); `environment:` в compose со значениями из `.env`; в образе настроек с секретами нет |
| 5 | Корректное завершение по сигналу | exec-форма `CMD`, `init: true`, `--timeout-graceful-shutdown 15` < `stop_grace_period: 20s`; при остановке приложения закрывается пул БД (`app/main.py`) |
| 6 | Compose для приложения и БД | `docker-compose.yml`: `db`, `migrate`, `app1`, `app2`, `nginx` |
| 7 | Внутренняя сеть, том, healthcheck, порядок запуска | сети `app_net`/`db_net` (`internal: true`); том `db_data`; healthcheck у всех долгоживущих сервисов; `depends_on`: db healthy → migrate completed → app healthy → nginx |
| 8 | Порт БД не публикуется без необходимости | порта БД в основном файле нет; для разработки — `docker-compose.dev.yml`, только `127.0.0.1` |
| 9 | Данные сохраняются после пересоздания и обновления образа | именованный том; `container-check` шаг 11: `down`/`up` и новый тег образа с `--force-recreate` |
| 10 | Миграции, резервная копия и восстановление в контейнерной среде | `migrate` (разовый контейнер), `make container-migrate`, `make migrations-demo`; `make backup`/`restore` через `docker compose exec db`; `make restore-new-volume` |
| 11 | Обоснованные ограничения ресурсов | `deploy.resources.limits` у всех сервисов; обоснование — [`containers.md`](containers.md), раздел 4 |
| 12 | `make container-check` | `scripts/container_check.sh` — 14 шагов |
| 13 | Запреты: `latest`, root, секреты в образе, отключённый healthcheck, лишние порты | `scripts/check_containers.py` (`make container-lint`, входит в `make verify`) и проверки во время работы в `container-check` |
| 14 | Изменения контейнерной среды — только после `make container-check` | [`workflow.md`](workflow.md); пункт в шаблоне merge request, его наличие проверяет `make policy` |

## Дополнительные задания

| № | Требование | Где реализовано |
|---|---|---|
| 1 | Nginx в отдельном контейнере | сервис `nginx`, конфигурация `nginx/nginx.conf` |
| 2 | Нет прямого доступа к приложению | у `app1`/`app2` нет `ports`; они только во внутренних сетях; `container-check` шаг 5 |
| 3 | Не менее двух экземпляров | `app1`, `app2` |
| 4 | Балансировка | `upstream warehouse_app`, round-robin; шаг 8 |
| 5 | Идентификатор экземпляра в ответе | заголовок `X-Instance-Id`, поле `instance` в `/healthz`; от nginx — `X-Upstream` |
| 6 | Остановка одного экземпляра — сервис доступен | шаг 9 (`kill app1` → 10 запросов, все 200) и шаг 10 (`stop app2`) |
| 7 | Исключение отказавшего узла / повтор / ограничение частоты | все три: `max_fails=2 fail_timeout=10s`, `proxy_next_upstream` (2 попытки), `limit_req` 20 запросов/с (шаг 14) |
| 8 | Что мешает горизонтальному масштабированию | [`containers.md`](containers.md), раздел 6 |

## Порядок проведения изменения (пункт 14)

```bash
git switch main && git pull
git switch -c feature/12-containers       # задача #12 «Контейнеризация»
# коммиты:
#   feat: идентификатор экземпляра в ответах и штатная остановка
#   feat: контейнеризация приложения и БД, Nginx и два экземпляра
#   chore: make container-check и статические запреты для контейнеров
#   docs: контейнерное окружение, ЛР4, версия 0.6.0
make verify                    # 8 шагов, включая container-lint
make container-check           # 14 шагов, вывод — в merge request
git push -u origin feature/12-containers
```

## Что показывать на защите

Перед защитой: `make up`, `make container-seed`.

**1. Сборка и запуск**

```bash
make container-check                 # все 14 шагов, итог «все проверки пройдены»
docker compose ps                    # db, app1, app2, nginx — healthy; migrate — Exited (0)
```

**2. Пользователь процесса — не root**

```bash
docker compose exec app1 id          # uid=10001(app) gid=10001(app)
docker compose top                   # ни одного процесса от root
docker compose exec nginx id         # uid=101(nginx)
```

**3. Сохранность данных после пересоздания**

```bash
curl -u admin:<пароль> -H 'Content-Type: application/json' \
     -d '{"code":"demo","name":"Демонстрация"}' http://127.0.0.1:8080/api/v1/units
docker compose down                  # контейнеры удалены
docker volume ls | grep db_data      # том на месте
make up
curl -s http://127.0.0.1:8080/api/v1/units | grep demo     # запись на месте
```

**4. Корректное завершение по сигналу**

```bash
time docker compose stop app2        # 1–2 с, не 20 (нет SIGKILL по таймауту)
docker compose logs --tail 8 app2    # Shutting down → Waiting for application shutdown
                                     # → «app-2 остановлен: соединения с БД закрыты»
                                     # → Application shutdown complete → Finished server process
docker inspect -f '{{.State.ExitCode}}' $(docker compose ps -aq app2)   # 143 (сам по SIGTERM), не 137
docker compose start app2
```

**5. Восстановление БД в новый том**

```bash
KEEP_RESTORED=1 make restore-new-volume
docker volume ls | grep restore-check                      # новый том
docker compose -p warehouse-restore-check down -v          # убрать после показа
```

**Дополнительно — балансировка и отказ**

```bash
for i in $(seq 6); do curl -s http://127.0.0.1:8080/healthz; echo; done   # instance чередуется
docker compose kill app1
for i in $(seq 6); do curl -s -o /dev/null -w '%{http_code} ' http://127.0.0.1:8080/healthz; done
docker compose logs --tail 10 nginx  # upstream=172.30.10.11:8000, 172.30.10.12:8000 — повтор
docker compose start app1
```

## Возможные вопросы

- **Зачем `migrate` отдельным контейнером?** Если миграции запустит каждый
  экземпляр при старте, два экземпляра применят их одновременно. Разовый
  контейнер выполняет миграции один раз, а приложение стартует только после
  его успешного завершения.
- **Почему nginx знает IP-адреса, а не имена?** Имена nginx разрешает при
  запуске. Если экземпляр в этот момент остановлен, nginx не запустится.
  Адреса фиксированы в `docker-compose.yml`.
- **Почему код завершения 143, а не 0?** uvicorn штатно обработал `SIGTERM`
  и повторно поднял сигнал, чтобы родитель знал причину остановки. Ошибкой
  был бы код 137: процесс убит, потому что не завершился вовремя.
- **Где пароли?** Только в `.env`, который не отслеживается git и не попадает
  в контекст сборки. В контейнер они передаются переменными при запуске
  (`container-check` шаг 6).
