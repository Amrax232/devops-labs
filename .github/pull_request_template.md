## Задача

Closes #<номер задачи>

## Что изменено

<!-- Список изменений по существу -->

## Как проверялось

- [ ] `make verify` проходит локально, `ci-gate` в CI — зелёный
- [ ] изменена контейнерная среда (Dockerfile, docker-compose*.yml, nginx/) —
      `make container-check` проходит, вывод приложен; иначе — не применимо
- [ ] новое поведение закрыто тестом
- [ ] документация обновлена (README / docs)

## Критические файлы

- [ ] изменений в критических файлах нет
- [ ] изменены критические файлы (перечислить и пояснить; список — отчёт
      «Критические файлы» этого merge request):

<!-- Makefile, Dockerfile, .dockerignore, docker-compose*.yml, nginx/**, alembic.ini, migrations/**, app/config.py,
     app/db.py, .env.example, .gitignore, requirements*.txt, pyproject.toml -->

## Секреты

- [ ] в diff нет `.env`, паролей, ключей и дампов базы
