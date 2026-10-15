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

.DEFAULT_GOAL := help

.PHONY: help setup lock run format lint sast quality policy secrets \
	    test test-unit test-api test-db test-integration coverage mutation \
	    migrate makemigration migrations-demo seed backup restore restore-demo \
	    verify up down container-check clean

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
	@echo "Готово. Дальше: make up && make migrate && make run"

lock: ## Зафиксировать точные версии всех зависимостей в requirements.lock
	$(BIN)/pip freeze --exclude-editable > requirements.lock
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

# -------------------------------------------------------------------- тесты
test: ## Быстрые тесты: unit + API (без PostgreSQL)
	$(BIN)/pytest tests/unit tests/api

test-unit: ## Unit-тесты правил предметной области
	$(BIN)/pytest tests/unit

test-api: ## Тесты HTTP API на изолированной SQLite-базе
	$(BIN)/pytest tests/api

test-db: ## Поднять PostgreSQL и подготовить тестовую базу $(TEST_DB)
	@docker compose up -d db > /dev/null
	@for i in $$(seq 1 30); do \
	    docker compose exec -T db pg_isready -q -U $(PG_USER) && break; sleep 1; \
	done
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

seed: ## Наполнить базу демонстрационными данными
	$(BIN)/python -m scripts.seed

backup: ## Резервная копия базы в backups/ (с проверкой и контрольной суммой)
	./scripts/backup.sh

restore: ## Восстановление: make restore FILE=backups/<файл>.dump
	./scripts/restore.sh "$(FILE)"

restore-demo: ## Копия → повреждение данных → восстановление → сверка
	./scripts/restore_demo.sh

# ---------------------------------------------------- единый проверочный контур
verify: ## ВСЕ обязательные проверки — запускать перед каждым merge request
	@echo "==> 1/7 policy: политика качества"
	@$(MAKE) --no-print-directory policy
	@echo "==> 2/7 secrets: секреты не в репозитории"
	@$(MAKE) --no-print-directory secrets
	@echo "==> 3/7 lint: формат и статический анализ"
	@$(MAKE) --no-print-directory lint
	@echo "==> 4/7 sast: анализ безопасности"
	@$(MAKE) --no-print-directory sast
	@echo "==> 5/7 test-db: тестовая база PostgreSQL"
	@$(MAKE) --no-print-directory test-db
	@echo "==> 6/7 coverage: unit, API и интеграционные тесты с покрытием"
	@$(MAKE) --no-print-directory coverage
	@echo "==> 7/7 mutation: мутационное тестирование"
	@$(MAKE) --no-print-directory mutation
	@echo "Все проверки пройдены. Отчёты: $(REPORTS)/"

# ---------------------------------------------------------------- контейнеры
up: ## Поднять контейнерное окружение (PostgreSQL)
	docker compose up -d

down: ## Остановить контейнерное окружение
	docker compose down

container-check: ## Проверить контейнерное окружение
	docker compose config -q
	docker compose ps
	docker compose exec -T db pg_isready -U $(PG_USER)

clean: ## Удалить временные файлы и отчёты
	rm -rf .pytest_cache .ruff_cache .coverage $(REPORTS)
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
