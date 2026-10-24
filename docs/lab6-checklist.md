# Лабораторная работа №6 — что сделано и что показывать на защите

Результат работы: **успешная сборка не равна успешному релизу** — версия
принимается только после проверки в целевой среде. Подробности — [`cd.md`](cd.md).

## Соответствие заданию

| № | Требование | Где реализовано |
|---|---|---|
| 1 | Отдельное тестовое окружение | ВМ `warehouse-stage` 192.168.56.20 (Debian 12): своя база, свои пароли; подготовка — `deploy/common/00-base-setup.sh stage`, `deploy/stage/10…40-*.sh` |
| 2 | Доступ pipeline к серверу через отдельную учётную запись | self-hosted runner под системным пользователем `deploy`: без пароля, без SSH, без sudo, только группа `docker` (`20-deploy-user.sh`, `30-github-runner.sh`) |
| 3 | Образ из registry, без пересборки на сервере | `docker-compose.deploy.yml`: `build: !reset`, `pull_policy: never`; `deploy.sh`: `docker pull` + `up --no-build`; контроль — `make container-lint` |
| 4 | Настройки окружения отдельно от образа | `/opt/warehouse-stage/env/stage.env` на сервере (600); в репозитории только `deploy/stage/stage.env.example` |
| 5 | Автоматическое развёртывание после публикации | `.github/workflows/deploy.yml`: `workflow_run` после успешного CI (CI на `main` публикует образ) |
| 6 | Ограничение веткой, тегом или ручным подтверждением | окружение `staging` — только защищённая ветка `main`; проверка события и ветки в `if`; по желанию — Required reviewers (`setup_staging.sh --approve`) |
| 7 | Проверка после развёртывания: контейнеры, служебный адрес, версия, основной сценарий | `deploy.sh`: `compose_wait.sh` (все healthy, migrate = 0), образ контейнеров; `scripts/smoke_test.sh`: `/healthz`, `/readyz`, `/version`, сквозной сценарий поступления и списания |
| 8 | `/version` | `GET /version`: версия, коммит образа (`APP_REVISION` ← `VCS_REF`), окружение, экземпляр |
| 9 | Выпуск не успешен при падении проверки | `deploy.sh` → код 1, задание CD красное, в истории `FAILED`; затем автоматический возврат |
| 10 | Развёртывание конкретного тега и ручной возврат | Run workflow: `deploy` + `tag`, `rollback`; на сервере `deploy.sh deploy <тег>` / `rollback` |
| 11 | Ограничение одновременных развёртываний | `concurrency: deploy-staging` (`cancel-in-progress: false`) + `flock` в `deploy.sh` |
| 12 | Сквозной выпуск функции | фильтр материалов по месту хранения (задача #15) — порядок ниже |
| 13 | Неудачный выпуск и возврат предыдущей версии | `simulate: healthcheck` / `scenario` → выпуск не принят → автоматический возврат; `action: rollback` — ручной |

## Сквозной выпуск функции (пункт 12)

Функция — фильтр материалов по месту хранения:
`GET /api/v1/materials?location=A-01`. Патчи для неё лежат в архиве
(`patches/lab6-e2e/`).

```bash
# 1. задача
gh issue create --title "Фильтр материалов по месту хранения" \
  --body "GET /api/v1/materials?location=<ячейка>. Проверка: тест + сценарий в staging"
# 2. ветка от актуального main
git switch main && git pull && git switch -c feature/15-materials-location
git am ~/lab6-cd/patches/lab6-e2e/*.patch
# 3. локальные проверки
make verify
# 4. merge request → CI (ci-gate) → одобрение → Merge
git push -u origin feature/15-materials-location && gh pr create --base main --fill
gh pr checks --watch
# 5. CI на main публикует образ ghcr.io/<владелец>/warehouse-inventory:<SHA>
# 6. CD (staging) запускается сам: развёртывание и проверка выпуска
gh run watch "$(gh run list --workflow deploy.yml -L 1 --json databaseId -q '.[0].databaseId')"
# 7. проверка релиза вручную
curl -s http://192.168.56.20:8080/version                   # коммит = SHA слияния
curl -s "http://192.168.56.20:8080/api/v1/materials?location=MAIN" | jq length
```

## Что показывать на защите

Все сценарии запускаются вручную: Actions → **CD (staging)** → **Run
workflow**. Перед защитой проверьте, что работает последняя версия `main`
(`action: status`).

| № | Проверка | Параметры запуска | Что видно |
|---|---|---|---|
| 1 | Неверный тег | `deploy`, tag `no-such-tag` | «в реестре нет образа … (неверный тег). Выпуск не начат, работает прежняя версия»; задание красное; `/version` не изменился |
| 2 | Отсутствующая переменная | `deploy`, simulate `missing-var` | «не заданы переменные окружения: AUTH_PASSWORD»; ничего не перезапускалось |
| 3 | Неуспешный healthcheck | `deploy`, simulate `healthcheck` | `container … is unhealthy` → «выпуск не принят» → возврат предыдущей версии → её проверка пройдена; задание красное |
| 4 | Приложение запускается, но основной сценарий не работает | `deploy`, simulate `scenario` | контейнеры healthy, `/healthz` ok, но `POST /api/v1/units: код 401, ожидался 201` → выпуск не принят → возврат |
| 5 | Недоступный registry | `deploy`, simulate `registry` | 3 попытки `lookup registry.invalid: no such host` → выпуск не начат |
| 6 | Возврат предыдущей версии | `rollback` | «возврат: sha-B → sha-A», проверка выпуска пройдена; `/version` показывает коммит A |

В сценариях 3 и 4 тег можно не указывать — разворачивается последний коммит
`main`. Если он уже работает, после сбоя он же развернётся заново, без
имитации. Нагляднее указать другой тег, например предыдущий коммит `main`:
тогда видно, что после сбоя вернулась именно работавшая версия.

На сервере (SSH `deployer@192.168.56.20`):

```bash
cd /opt/actions-runner/_work/<репозиторий>/<репозиторий>
sudo -u deploy ./deploy/stage/deploy.sh status     # версия, стек, история выпусков
sudo -u deploy docker compose -p warehouse-stage ps
id deploy                                          # uid, группы: deploy, docker — без sudo
sudo ls -l /opt/warehouse-stage/env/                # stage.env, права -rw-------
ls /opt/warehouse-stage/releases/                  # файлы выпусков по коммитам
```

## Возможные вопросы

- **Почему runner на сервере, а не SSH из GitHub?** ВМ находится за NAT
  VirtualBox, и снаружи к ней не подключиться. Runner сам забирает задания
  исходящим соединением, поэтому входящих портов из интернета не нужно.
- **Почему не собрать образ на сервере?** Это был бы уже другой образ, не
  тот, что прошёл CI и анализ trivy. В реестре лежит проверенный артефакт, и
  именно его разворачиваем.
- **Как узнать, что работает?** `GET /version` возвращает коммит образа. Его
  сверяет `smoke_test.sh`; `deploy.sh status` показывает историю выпусков.
- **Почему возврат не откатывает миграции?** Миграции пишутся совместимыми
  назад: сначала расширяем схему, удаляем старое отдельным выпуском. Перед
  каждым выпуском делается копия БД.
- **Что, если два выпуска запустят одновременно?** Второй встанет в очередь
  (`concurrency`), а ручной запуск на сервере будет ждать блокировку (`flock`).
