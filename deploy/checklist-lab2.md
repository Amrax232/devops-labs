# Лабораторная работа №2 — соответствие требованиям и порядок защиты

## Что где сделано

| Требование задания | Где реализовано |
|---|---|
| 1. Две Linux-машины без графики | Debian 13 netinst: `app`, `db` |
| 2. Сеть, постоянные адреса, SSH по ключам | `common/interfaces.example`, `common/00-base-setup.sh`, `common/ssh-hardening.conf` |
| 3. Запрет root по SSH, отдельные пользователи | `PermitRootLogin no`; `deployer` — администрирование, `warehouse` — запуск сервиса |
| 4. Права на файлы и каталоги | `10-install-runtime.sh`: `/opt/warehouse` 750, `/etc/warehouse/warehouse.env` 640 root:warehouse |
| 5. Среда выполнения и СУБД | `app/10-install-runtime.sh` (Python 3.13), `db/10-install-postgres.sh` (PostgreSQL 17) |
| 6. База и пользователь СУБД с минимальными правами | роль `warehouse` без SUPERUSER/CREATEDB/CREATEROLE, `REVOKE ALL ... FROM PUBLIC` |
| 7. Развёртывание без контейнеров | `app/20-deploy-app.sh`: git + venv + миграции |
| 8. systemd-сервис | `app/warehouse.service`, `systemctl enable` в скрипте выкладки |
| 9. Автоматический перезапуск | `Restart=always`, `RestartSec=5`, `StartLimitBurst=5` |
| 10. Firewall | `db/20-firewall-db.sh`, `app/30-firewall-app.sh` |
| 11. Конфигурация отдельно от кода | `EnvironmentFile=/etc/warehouse/warehouse.env`, шаблон `warehouse.env.example` |
| 12. Скрипты повторяемого развёртывания | весь каталог `deploy/`, инструкция в `deploy/README.md` |
| 13. Зафиксированные правила безопасности | `deploy/security.md` |

## Сценарии проверки на защите

### 1. Перезагрузка обеих машин

```bash
sudo reboot        # сначала на db, затем на app
```

После загрузки ничего руками не запускаем:

```bash
systemctl is-enabled warehouse     # enabled
systemctl is-active warehouse      # active
curl http://192.168.56.10:8000/readyz   # {"status":"ok","database":"ok"}
```

### 2. Диагностика при отказе базы данных

```bash
# на db
sudo systemctl stop postgresql

# на app
curl -s http://127.0.0.1:8000/healthz    # приложение живо: {"status":"ok",...}
curl -s http://127.0.0.1:8000/readyz     # {"status":"degraded","database":"unavailable"}
sudo journalctl -u warehouse -n 30       # в журнале видно ошибки подключения
systemctl status warehouse               # сервис active: упал не он, а база
```

Вывод, который нужно проговорить: сервис не падает из-за недоступной базы —
`/healthz` отвечает, что процесс жив, а `/readyz` честно сообщает, что работать
с данными нельзя. Именно так их и различают системы мониторинга.

```bash
sudo systemctl start postgresql          # восстановление
curl -s http://127.0.0.1:8000/readyz     # снова ok
```

### 3. Инструменты диагностики Linux

```bash
sudo ss -ltnp | grep 8000        # кто слушает порт
pgrep -a uvicorn                 # процесс приложения
ps -o pid,user,cmd -C uvicorn    # от какого пользователя работает (warehouse, не root)
sudo journalctl -u warehouse --since "10 min ago"
sudo journalctl -u warehouse -p err
systemctl cat warehouse          # текущий unit-файл
systemd-analyze verify /etc/systemd/system/warehouse.service
```

### 4. Изменение параметра unit-файла

Показательный параметр — задержка перезапуска:

```bash
sudo systemctl edit --full warehouse     # RestartSec=5 → RestartSec=15
sudo systemctl daemon-reload
sudo systemctl restart warehouse
systemctl show warehouse -p RestartUSec  # RestartUSec=15s — изменение применилось
```

Проверка, что перезапуск работает:

```bash
sudo pkill -9 -f uvicorn                 # имитируем аварийное завершение
systemctl status warehouse               # через 15 секунд сервис снова active
```

Возврат к исходному состоянию:

```bash
sudo systemctl edit --full warehouse     # вернуть RestartSec=5
sudo systemctl daemon-reload && sudo systemctl restart warehouse
systemctl show warehouse -p RestartUSec  # RestartUSec=5s
```

### 5. Сетевая изоляция базы данных

С хоста (или с третьей машины в той же сети):

```bash
# база недоступна
nc -zv 192.168.56.11 5432        # connection refused / timed out
psql -h 192.168.56.11 -U warehouse -d warehouse   # не подключается

# приложение доступно
curl -u admin:<пароль> http://192.168.56.10:8000/api/v1/materials
```

С сервера приложения — та же база доступна:

```bash
ssh deployer@192.168.56.10
pg_isready -h 192.168.56.11 -p 5432      # accepting connections
```

### 6. Дополнительные вопросы, которые обычно задают

- **Почему приложение не от root?** Если процесс скомпрометируют, злоумышленник
  получит права только на `/opt/warehouse` и не сможет изменить систему.
- **Что произойдёт, если сервис падает постоянно?** `StartLimitBurst=5` за
  `StartLimitIntervalSec=60`: после пяти падений за минуту systemd прекращает
  попытки и помечает сервис `failed`, чтобы не крутить бесконечный цикл.
  Сброс — `systemctl reset-failed warehouse`.
- **Где пароли?** Только в `/etc/warehouse/warehouse.env` (640 root:warehouse) и
  в самой СУБД. В репозитории — шаблоны со значением `CHANGE_ME`.
- **Почему база слушает не 0.0.0.0?** `listen_addresses` ограничивает СУБД
  адресом лабораторной сети, `pg_hba.conf` — конкретным адресом приложения,
  `ufw` — третий рубеж. Любой из них по отдельности можно обойти ошибкой в
  конфигурации, вместе — нет.
