# Единый набор команд проекта.
# Все проверки, которые выполняет преподаватель, запускаются этими же командами.
# Полный проверочный контур — `make verify`: без него изменение не принимается.

SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
VENV ?= .venv
BIN := $(VENV)/bin
PY ?= python3
REPORTS := reports

# Значение переменной из .env (если файла или переменной нет — пусто)
env_value = $(shell grep -E '^$(1)=' .env 2>/dev/null | tail -1 | cut -d= -f2-)
PG_USER := $(or $(call env_value,POSTGRES_USER),warehouse)
TEST_DB ?= warehouse_test
HTTP_PORT := $(or $(call env_value,HTTP_PORT),8080)
# PostgreSQL с портом на 127.0.0.1 — для разработки из .venv (make run, тесты)
COMPOSE_DEV := docker compose -f docker-compose.yml -f docker-compose.dev.yml
# Образ: тег берётся из окружения (в CI — версия и commit SHA), затем из .env
APP_VERSION ?= $(or $(call env_value,APP_VERSION),0.7.0)
IMAGE ?= warehouse-inventory:$(APP_VERSION)
DIST := dist
# Сканеры запускаются в контейнерах с закреплёнными версиями: локально и в CI
# работает один и тот же инструмент одной и той же версии.
GITLEAKS_IMAGE ?= zricethezav/gitleaks:v8.21.2
TRIVY_IMAGE ?= aquasec/trivy:0.56.2
TRIVY_CACHE ?= $(HOME)/.cache/trivy
TRIVY = docker run --rm -u $(DOCKER_USER) -e HOME=/tmp -v "$(CURDIR):/work" -v "$(TRIVY_CACHE):/cache" \
	-w /work $(TRIVY_IMAGE) --cache-dir /cache
DOCKER_USER := $(shell id -u):$(shell id -g)

.DEFAULT_GOAL := help

.PHONY: help setup lock run format lint sast quality policy secrets \
	    test test-unit test-api test-db test-integration coverage mutation \
	    migrate makemigration migrations-demo seed backup restore restore-demo \
	    verify build up down ps logs dev-db container-lint container-migrate \
	    container-seed restore-new-volume container-check clean \
	    secrets-scan deps-audit migrations-check backup-check image-save image-scan \
	    publish critical-changes ci

help: ## Показать список команд
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ----------------------------------------------------------------- окружение
setup: ## Первоначальная настройка: venv, зависимости, .env
	$(PY) -c 'import sys; assert sys.version_info >= (3, 11), "нужен Python 3.11+"'
	$(PY) -m venv $(VENV)
	$(BIN)/pip install --quiet --upgrade pip
	@if [ -f requirements.lock ]; then \
	    echo "Установка по зафиксированным версиям (requirements.lock)"; \
	    $(BIN)/pip install --quiet -r requirements-dev.txt -c requirements.lock; \
	else \
	    $(BIN)/pip install --quiet -r requirements-dev.txt; \
	    echo "requirements.lock нет — выполните make lock и закоммитьте файл"; \
	fi
	@test -f .env || (cp .env.example .env && echo "Создан .env из .env.example")
	@echo "Готово. Контейнерное окружение: make up (http://127.0.0.1:8080/docs)"
	@echo "Разработка из .venv: make dev-db && make migrate && make run"

lock: ## Зафиксировать точные версии всех зависимостей в requirements.lock
	$(BIN)/pip freeze --exclude-editable | grep -v "^pkg[-_]resources==" > requirements.lock
	@echo "Версии зафиксированы: requirements.lock ($$(wc -l < requirements.lock) пакетов)"

run: ## Локальный запуск приложения
	$(BIN)/python -m app

# ------------------------------------------------- качество кода и безопасность
format: ## Привести код к единому формату
	$(BIN)/ruff format .
	$(BIN)/ruff check --fix .

lint: ## Линтер: формат и статический анализ (ruff), без исправлений
	$(BIN)/ruff format --check .
	$(BIN)/ruff check .

sast: ## Статический анализ безопасности (bandit), отчёт в reports/bandit.json
	@mkdir -p $(REPORTS)
	$(BIN)/bandit -c pyproject.toml -r app -ll -ii
	@$(BIN)/bandit -c pyproject.toml -r app -ll -ii -q -f json -o $(REPORTS)/bandit.json
	@echo "Отчёт SAST: $(REPORTS)/bandit.json"

quality: lint sast ## Линтер и SAST вместе

policy: ## Запрет пропуска тестов, снижения порогов и исключений без обоснования
	$(BIN)/python scripts/check_policy.py

secrets: ## Секреты и данные не отслеживаются git
	./scripts/check_secrets.sh

secrets-scan: ## Поиск секретов во всей истории git (gitleaks), отчёт reports/gitleaks.json
	@mkdir -p $(REPORTS)
	docker run --rm -u $(DOCKER_USER) -e HOME=/tmp -v "$(CURDIR):/repo" -w /repo \
	    --entrypoint sh $(GITLEAKS_IMAGE) -c 'git config --global --add safe.directory /repo \
	    && gitleaks detect --source /repo --config /repo/.gitleaks.toml --redact \
	       --no-banner --verbose --report-format json --report-path /repo/$(REPORTS)/gitleaks.json'

deps-audit: ## Уязвимости зависимостей из requirements.lock (pip-audit), отчёт reports/pip-audit.json
	$(BIN)/python scripts/deps_audit.py

# -------------------------------------------------------------------- тесты
test: ## Быстрые тесты: unit + API (без PostgreSQL)
	$(BIN)/pytest tests/unit tests/api

test-unit: ## Unit-тесты правил предметной области
	$(BIN)/pytest tests/unit

test-api: ## Тесты HTTP API на изолированной SQLite-базе
	$(BIN)/pytest tests/api

test-db: dev-db ## Поднять PostgreSQL и подготовить тестовую базу $(TEST_DB)
	@docker compose exec -T db psql -U $(PG_USER) -d postgres -tAc \
	    "SELECT 1 FROM pg_database WHERE datname = '$(TEST_DB)'" | grep -q 1 \
	    || docker compose exec -T db createdb -U $(PG_USER) $(TEST_DB)
	@echo "Тестовая база $(TEST_DB) готова"

test-integration: test-db ## Интеграционные тесты на PostgreSQL: миграции и БД
	$(BIN)/pytest tests/integration

coverage: ## Все тесты + отчёты: reports/junit.xml, coverage.xml, coverage-html/
	@mkdir -p $(REPORTS)
	$(BIN)/pytest tests --cov --cov-report=term-missing --cov-report=xml \
	    --cov-report=html --junitxml=$(REPORTS)/junit.xml

mutation: ## Мутационное тестирование app/domain.py, отчёт reports/mutation.txt
	$(BIN)/python scripts/mutation_test.py --target app/domain.py --tests tests/unit

# ----------------------------------------------------------- база данных
migrate: ## Применить миграции базы данных
	$(BIN)/alembic upgrade head

makemigration: ## Создать миграцию: make makemigration M="описание"
	$(BIN)/alembic revision --autogenerate -m "$(M)"

migrations-demo: ## Миграции на чистой и на заполненной базе (отдельная база)
	./scripts/migrations_demo.sh

migrations-check: dev-db ## Миграции: с нуля, alembic check, линейность, откат и повтор
	./scripts/migrations_check.sh

seed: ## Наполнить базу демонстрационными данными
	$(BIN)/python -m scripts.seed

backup: ## Резервная копия базы в backups/ (с проверкой и контрольной суммой)
	./scripts/backup.sh

restore: ## Восстановление: make restore FILE=backups/<файл>.dump
	./scripts/restore.sh "$(FILE)"

restore-demo: ## Копия → повреждение данных → восстановление → сверка
	./scripts/restore_demo.sh

backup-check: dev-db ## Этап CI: миграции, демо-данные, копия → повреждение → восстановление
	@$(MAKE) --no-print-directory migrate
	@$(MAKE) --no-print-directory seed
	@$(MAKE) --no-print-directory restore-demo

# ---------------------------------------------------- единый проверочный контур
verify: ## ВСЕ обязательные проверки — запускать перед каждым merge request
	@echo "==> 1/10 policy: политика качества"
	@$(MAKE) --no-print-directory policy
	@echo "==> 2/10 secrets: секреты не в репозитории"
	@$(MAKE) --no-print-directory secrets
	@echo "==> 3/10 secrets-scan: поиск секретов в истории git"
	@$(MAKE) --no-print-directory secrets-scan
	@echo "==> 4/10 lint: формат и статический анализ"
	@$(MAKE) --no-print-directory lint
	@echo "==> 5/10 sast: анализ безопасности кода"
	@$(MAKE) --no-print-directory sast
	@echo "==> 6/10 deps-audit: уязвимости зависимостей"
	@$(MAKE) --no-print-directory deps-audit
	@echo "==> 7/10 container-lint: запреты для образа и compose"
	@$(MAKE) --no-print-directory container-lint
	@echo "==> 8/10 test-db: тестовая база PostgreSQL"
	@$(MAKE) --no-print-directory test-db
	@echo "==> 9/10 coverage: unit, API и интеграционные тесты с покрытием"
	@$(MAKE) --no-print-directory coverage
	@echo "==> 10/10 mutation: мутационное тестирование"
	@$(MAKE) --no-print-directory mutation
	@echo "Все проверки пройдены. Отчёты: $(REPORTS)/"

# ---------------------------------------------------------------- контейнеры
# Изменения Dockerfile, docker-compose*.yml и nginx/ принимаются только после
# успешного make container-check (docs/containers.md, docs/workflow.md).
build: ## Собрать образ приложения (нужен закоммиченный requirements.lock)
	@test -f requirements.lock || { \
	    echo "Нет requirements.lock: выполните make lock и закоммитьте файл" >&2; exit 1; }
	docker compose build

up: build ## Поднять окружение: БД, миграции, app1 и app2, Nginx
	docker compose up -d --remove-orphans
	./scripts/compose_wait.sh
	@echo "Сервис: http://127.0.0.1:$(HTTP_PORT)/docs  (только через Nginx)"

down: ## Остановить окружение (данные в томе db_data сохраняются)
	docker compose down

ps: ## Состояние контейнеров
	docker compose ps -a

logs: ## Журналы: make logs [S=app1]
	docker compose logs --tail=100 -f $(S)

dev-db: ## Только PostgreSQL с портом на 127.0.0.1 — для make run и тестов
	@$(COMPOSE_DEV) up -d db > /dev/null
	@for i in $$(seq 1 60); do \
	    docker compose exec -T db pg_isready -q -h 127.0.0.1 -U $(PG_USER) && break; sleep 1; \
	done
	@docker compose exec -T db pg_isready -q -h 127.0.0.1 -U $(PG_USER)

container-lint: ## Статические запреты: latest, root, секреты, healthcheck, порты
	$(BIN)/python scripts/check_containers.py

container-migrate: ## Миграции в контейнерной среде
	docker compose run --rm migrate

container-seed: ## Демонстрационные данные в контейнерной среде
	docker compose exec -T app1 python -m scripts.seed

restore-new-volume: ## Копия → новый пустой том → восстановление → сверка
	./scripts/restore_new_volume.sh "$(FILE)"

container-check: ## Полная проверка контейнерной среды (обязательна перед её изменением)
	./scripts/container_check.sh

image-save: ## Сохранить образ $(IMAGE) в dist/image.tar (его анализирует trivy и публикует CI)
	@mkdir -p $(DIST)
	docker save $(IMAGE) -o $(DIST)/image.tar
	@echo "Образ $(IMAGE) сохранён: $(DIST)/image.tar ($$(du -h $(DIST)/image.tar | cut -f1))"

image-scan: image-save ## Анализ образа (trivy): отчёт reports/trivy.txt, CRITICAL с исправлением — ошибка
	@mkdir -p $(REPORTS) $(TRIVY_CACHE)
	$(BIN)/python scripts/deps_audit.py --trivyignore $(REPORTS)/trivyignore
	@echo "Отчёт HIGH и CRITICAL: $(REPORTS)/trivy.txt"
	@$(TRIVY) image --input /work/$(DIST)/image.tar --scanners vuln \
	    --ignorefile /work/$(REPORTS)/trivyignore --severity HIGH,CRITICAL \
	    --format table --output /work/$(REPORTS)/trivy.txt --exit-code 0
	@echo "Запрет: CRITICAL, для которых есть исправление"
	$(TRIVY) image --input /work/$(DIST)/image.tar --scanners vuln \
	    --ignorefile /work/$(REPORTS)/trivyignore --severity CRITICAL --ignore-unfixed \
	    --format table --exit-code 1

publish: ## Только CI: опубликовать проверенный образ: make publish REGISTRY_IMAGE=ghcr.io/<владелец>/<имя>
	@test -n "$(REGISTRY_IMAGE)" || { echo "Укажите REGISTRY_IMAGE" >&2; exit 1; }
	@test -n "$$GITHUB_SHA" || { echo "Публикация выполняется только в CI" >&2; exit 1; }
	docker load -i $(DIST)/image.tar
	@for tag in "$$GITHUB_SHA" "sha-$${GITHUB_SHA:0:7}" "$(APP_VERSION)"; do \
	    docker tag $(IMAGE) "$(REGISTRY_IMAGE):$$tag"; \
	    docker push --quiet "$(REGISTRY_IMAGE):$$tag"; \
	    echo "Опубликован $(REGISTRY_IMAGE):$$tag"; \
	done
	@docker image inspect -f 'Digest: {{index .RepoDigests 0}}' "$(REGISTRY_IMAGE):$$GITHUB_SHA"

critical-changes: ## Изменённые критические файлы и число тестов: make critical-changes [BASE=origin/main]
	$(PY) scripts/critical_changes.py $(or $(BASE),origin/main)

ci: ## Весь pipeline CI локально, в том же порядке
	@$(MAKE) --no-print-directory verify
	@$(MAKE) --no-print-directory migrations-check
	@$(MAKE) --no-print-directory backup-check
	@$(MAKE) --no-print-directory container-check
	@$(MAKE) --no-print-directory image-scan

clean: ## Удалить временные файлы и отчёты
	rm -rf .pytest_cache .ruff_cache .coverage $(REPORTS)
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
