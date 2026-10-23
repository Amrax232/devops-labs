# Лабораторная работа №5 — что сделано и что показывать на защите

Цель: CI — независимый и обязательный барьер перед созданием и публикацией
артефакта. Подробности — [`ci.md`](ci.md).

## Соответствие заданию

| № | Требование | Где реализовано |
|---|---|---|
| 1 | Выбор системы CI | GitHub Actions: репозиторий уже на GitHub, защита веток, CODEOWNERS и реестр образов `ghcr.io` встроены |
| 2 | Подключение репозитория | `.github/workflows/ci.yml` в репозитории; настройка — `scripts/setup_github.sh` |
| 3 | Запуск при отправке изменений, при merge request и при изменении `main` | `on: push` (все ветки), `pull_request` (в `main`) |
| 4 | Те же команды, что локально | каждый этап вызывает только make-цели; `make verify` и `make ci` — те же проверки на машине разработчика |
| 5 | Этапы: стиль, тесты, миграции, резервное копирование, безопасность, контейнеры, сборка и публикация | задания 1–7 в `ci.yml` |
| 6 | Отдельная тестовая БД | свой PostgreSQL в каждом задании; `warehouse_test` (`make test-db`); `warehouse_migrations_check`; защита по имени `_test` |
| 7 | Сохранение отчётов тестов и анализаторов | артефакты `reports-tests`, `reports-security`, `reports-container` (14 дней) |
| 8 | Кэширование зависимостей | `setup-python` с `cache: pip`; `actions/cache` для базы trivy |
| 9 | Тег образа связан с commit SHA | `<версия>-<SHA7>` при сборке; в реестре `:<SHA>`, `:sha-<SHA7>`, `:<версия>-<SHA7>`; метка `org.opencontainers.image.revision` |
| 10 | Нет публикации при падении проверки | этап 7: `needs` от всех этапов, повторная сверка результатов, только `push` в `main`, окружение `registry` |
| 11 | Пароли и токены в защищённых переменных CI | `CI_AUTH_PASSWORD`, `CI_POSTGRES_PASSWORD` (Secrets), `GITHUB_TOKEN`; `scripts/ci_env.sh` |
| 12 | Поиск секретов, проверка зависимостей, анализ образа | `make secrets-scan` (gitleaks), `make deps-audit` (pip-audit), `make image-scan` (trivy); Dependabot |
| 13 | Защита критических файлов | `.github/CODEOWNERS`; `make policy` (тесты, пороги, pipeline, исключения) |
| 14 | Обязательная проверка изменений критических файлов | защита `main`: Require review from Code Owners, обязательный `ci-gate`, правила и для администраторов |
| 15 | Попытку удалить тест, отключить проверку или ослабить правило нельзя принять незаметно | `make policy` падает на этапе 1; отчёт «Критические файлы» с аннотациями; одобрение владельца |
| 16 | Успешный CI для корректного изменения, остановка — для дефектного | `scripts/ci_demo.sh ok` и сценарии с дефектами (ниже) |

## Порядок проведения изменения

```bash
git switch main && git pull
git switch -c feature/13-ci                # задача #13 «Непрерывная интеграция»
# коммиты: ci: … / chore: … / docs: …
make verify
git push -u origin feature/13-ci
gh pr create --base main --fill            # CI запускается автоматически
# одобрение второго участника → Merge → CI на main → публикация образа
```

## Демонстрационные сценарии

Каждый сценарий создаёт ветку от `main` с одним коммитом. После этого:
`git push -u origin demo/<сценарий>` и merge request в `main`.

| Сценарий | Что меняется | Где остановится CI | Ожидаемый результат |
|---|---|---|---|
| `ok` | строка в документации | — | все этапы зелёные, `ci-gate` успешен, кнопка Merge доступна после одобрения |
| `break-test` | в правиле списания `>` заменено на `>=` | 2. Тесты | `test_whole_stock_can_be_written_off` и др. падают |
| `break-migration` | миграция `0005` с несуществующей таблицей | 2. Тесты, 3. Миграции | `make migrations-check` падает на `upgrade head` |
| `add-secret` | токен GitHub в `app/demo_settings.py` | 5. Безопасность | gitleaks: `github-pat`, `leaks found: 1` |
| `delete-test` | удалён тест списания | 1. Стиль и политика | «тестовых функций 105, а должно быть не меньше 106»; отчёт: «удалено 1» |
| `skip-test` | тест помечен `skip` | 1. Стиль и политика | «пропуск теста без обоснования» |
| `lower-threshold` | порог покрытия 50 % | 1. Стиль и политика | «порог покрытия 50% ниже допустимого 80%» |
| `disable-check` | из pipeline убран `make mutation` | 1. Стиль и политика | «этап test не выполняет make mutation» |

Во всех дефектных сценариях `6. Контейнерная проверка` и `7. Публикация`
получают статус «skipped», а `ci-gate` — красный. Влить такой merge request
защита ветки не даёт.

## Что показывать на защите

**1. Поломка теста или миграции — pipeline останавливается**

```bash
./scripts/ci_demo.sh break-test && git push -u origin demo/break-test
gh pr create --base main --title "Демо: ошибка в правиле" --body "Демонстрация остановки CI"
gh pr checks --watch                     # «2. Тесты» — fail, дальше — skipping
```

**2. Тестовый секрет обнаружен**

```bash
./scripts/ci_demo.sh add-secret && git push -u origin demo/add-secret
# «5. Безопасность» → шаг make secrets-scan: RuleID github-pat, File app/demo_settings.py
make secrets-scan                        # то же самое локально
```

**3. Образ не публикуется после ошибки**

- в запуске дефектной ветки: «7. Публикация образа» — skipped;
- Packages репозитория (`ghcr.io/<владелец>/warehouse-inventory`): тегов с SHA
  дефектного коммита нет, есть только теги коммитов `main` с зелёным CI.

```bash
git rev-parse --short HEAD               # SHA дефектного коммита
docker pull ghcr.io/<владелец>/warehouse-inventory:sha-<SHA7>    # manifest unknown
```

**4. Защита критических файлов**

```bash
./scripts/ci_demo.sh delete-test && git push -u origin demo/delete-test
```

- merge request: «Критические файлы» — аннотация «Удалено тестовых функций: 1»;
- «1. Стиль и политика» — красный;
- на странице MR: «Review required — Code owner review required», кнопка
  Merge заблокирована;
- Settings → Branches → правило для `main`.

**5. Почему локальные и серверные проверки должны совпадать** — см.
[`ci.md`](ci.md), раздел 2. Если они расходятся, разработчик не может
воспроизвести ошибку сервера, а сервер может пропустить то, что ловится
локально. В проекте совпадение обеспечено построением:

- CI вызывает только make-цели;
- зависимости ставятся из одного `requirements.lock`;
- сканеры одинаковых версий запускаются из Docker-образов.

Уборка после показа:

```bash
git switch main
for b in $(git branch --list 'demo/*' | tr -d ' '); do
    git branch -D "$b"
    git push origin --delete "$b"
done
```
