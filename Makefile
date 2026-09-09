# Единый набор команд проекта.
# Все проверки, которые выполняет преподаватель, запускаются этими же командами.

SHELL := /bin/bash
VENV ?= .venv
BIN := $(VENV)/bin
PY ?= python3
BACKUP_DIR ?= backups

.DEFAULT_GOAL := help

.PHONY: help setup run test quality format migrate makemigration backup restore verify up down container-check clean

help: ## Показать список команд
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

setup: ## Первоначальная настройка: виртуальное окружение, зависимости, .env
	$(PY) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -r requirements-dev.txt
	@test -f .env || (cp .env.example .env && echo "Создан .env из .env.example")
	@echo "Готово. Дальше: make up && make migrate && make run"

run: ## Локальный запуск приложения
	$(BIN)/python -m app

test: ## Автоматические тесты
	$(BIN)/pytest

quality: ## Форматирование кода и статический анализ
	$(BIN)/ruff format .
	$(BIN)/ruff check .

format: ## Отформатировать код
	$(BIN)/ruff format .
	$(BIN)/ruff check --fix .

migrate: ## Применить миграции базы данных
	$(BIN)/alembic upgrade head

makemigration: ## Создать миграцию: make makemigration M="описание"
	$(BIN)/alembic revision --autogenerate -m "$(M)"

backup: ## Резервная копия базы данных в каталог backups/
	./scripts/backup.sh

restore: ## Восстановление из копии: make restore FILE=backups/<файл>.dump
	./scripts/restore.sh "$(FILE)"

verify: ## Полный набор локальных проверок (запускать перед merge request)
	@echo "==> 1/3 проверка, что секреты не отслеживаются git"
	@! git ls-files --error-unmatch .env > /dev/null 2>&1 || (echo "ОШИБКА: файл .env попал в репозиторий" && exit 1)
	@echo "==> 2/3 качество кода"
	@$(MAKE) --no-print-directory quality
	@echo "==> 3/3 тесты"
	@$(MAKE) --no-print-directory test
	@echo "Все проверки пройдены."

up: ## Поднять контейнерное окружение (PostgreSQL)
	docker compose up -d

down: ## Остановить контейнерное окружение
	docker compose down

container-check: ## Проверить контейнерное окружение
	docker compose config -q
	docker compose ps
	docker compose exec -T db pg_isready -U $${POSTGRES_USER:-warehouse}

clean: ## Удалить временные файлы
	rm -rf .pytest_cache .ruff_cache **/__pycache__ __pycache__
