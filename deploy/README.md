# Развёртывание в Linux-среде (лабораторная работа №2)

Приложение разворачивается на двух виртуальных машинах Debian 13 без графической
оболочки и без контейнеров: системные пакеты, `systemd`, `ufw`, SSH по ключам.

```
      хост (Windows)
            │  192.168.56.1
            │
   ┌────────┴──────────────── сеть VirtualBox 192.168.56.0/24 ─────────────┐
   │                                                                       │
┌──┴───────────────────────┐                            ┌──────────────────┴──┐
│ app            │   5432/tcp только отсюда   │ db      │
│ 192.168.56.10            │ ─────────────────────────▶| 192.168.56.11        
│ Python 3.13 + uvicorn    │                            │ PostgreSQL 17       │
│ сервис warehouse.service │                            │ база warehouse      │
│ открыт порт 8000         │                            │ порт 5432 закрыт    │
└──────────────────────────┘                            └─────────────────────┘
```

## Состав каталога

| Файл | Где выполняется | Назначение |
|---|---|---|
| `common/00-base-setup.sh` | обе машины | пакеты, имя хоста, администратор `deployer`, ограничения SSH |
| `common/ssh-hardening.conf` | обе машины | конфигурация SSH: только ключи, без root |
| `common/interfaces.example` | обе машины | пример постоянной IP-адресации |
| `db/10-install-postgres.sh` | `db` | PostgreSQL, база и пользователь с минимальными правами |
| `db/20-firewall-db.sh` | `db` | 5432 только для сервера приложения |
| `app/10-install-runtime.sh` | `app` | Python, пользователь `warehouse`, каталоги и права |
| `app/warehouse.env.example` | `app` | шаблон `/etc/warehouse/warehouse.env` |
| `app/20-deploy-app.sh` | `app` | код, зависимости, миграции, unit-файл, перезапуск |
| `app/warehouse.service` | `app` | systemd-сервис с автозапуском и перезапуском |
| `app/30-firewall-app.sh` | `app` | открыты только SSH и 8000 |
| `app/status.sh` | `app` | диагностика одной командой |
| `security.md` | — | зафиксированные правила безопасности |
| `checklist-lab2.md` | — | что показывать на защите |

## Порядок развёртывания

### Шаг 1. Две виртуальные машины

В VirtualBox создайте две машины из образа `debian-12-netinst`: 1 ГБ ОЗУ и
10 ГБ диска достаточно. При установке снимите галочку с окружения рабочего
стола, оставьте только «standard system utilities» и «SSH server».

Каждой машине — два сетевых адаптера:

- **Адаптер 1** — NAT (интернет для `apt`);
- **Адаптер 2** — «Виртуальный адаптер хоста» (Host-only, сеть `192.168.56.0/24`).

Имена: `app` и `db`.

### Шаг 2. Постоянные адреса

На каждой машине от root отредактируйте `/etc/network/interfaces` по образцу
`common/interfaces.example` (для `db` адрес `192.168.56.11`), затем:

```bash
systemctl restart networking
ip -br addr        # убедитесь, что enp0s8 получил нужный адрес
```

Проверьте связь между машинами: `ping -c2 192.168.56.11`.

### Шаг 3. Базовая настройка и SSH по ключам

Скопируйте каталог `deploy/` на машины (например, `git clone` репозитория) и
выполните от root:

```bash
bash deploy/common/00-base-setup.sh app     # на app
bash deploy/common/00-base-setup.sh db      # на db
```

На своём компьютере создайте ключ и разложите его:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/warehouse -C "warehouse lab"
ssh-copy-id -i ~/.ssh/warehouse.pub deployer@192.168.56.10
ssh-copy-id -i ~/.ssh/warehouse.pub deployer@192.168.56.11
```

Убедитесь, что вход работает (`ssh -i ~/.ssh/warehouse deployer@192.168.56.10`),
и только после этого примените ограничения:

```bash
sudo systemctl restart ssh
sudo ufw --force enable
```

> Порядок важен: если перезапустить SSH до того, как ключ добавлен, попасть на
> машину можно будет только через консоль VirtualBox.

### Шаг 4. Сервер базы данных

```bash
ssh deployer@192.168.56.11
sudo DB_PASSWORD="$(openssl rand -base64 24)" bash deploy/db/10-install-postgres.sh
# запишите пароль — он понадобится на сервере приложения
sudo bash deploy/db/20-firewall-db.sh
```

### Шаг 5. Сервер приложения

```bash
ssh deployer@192.168.56.10
sudo bash deploy/app/10-install-runtime.sh
sudo vim /etc/warehouse/warehouse.env     # вписать пароль БД и пароль API
sudo REPO_URL=https://github.com/<логин>/warehouse-inventory.git \
     bash deploy/app/20-deploy-app.sh
sudo bash deploy/app/30-firewall-app.sh
```

Проверка с хоста: <http://192.168.56.10:8000/healthz> и
`curl -u admin:<пароль> http://192.168.56.10:8000/api/v1/materials`.

### Шаг 6. Наполнение данными (необязательно)

```bash
cd /opt/warehouse/current
sudo -u warehouse /opt/warehouse/venv/bin/python -m scripts.seed
```

## Обновление версии

```bash
ssh deployer@192.168.56.10
sudo bash deploy/app/20-deploy-app.sh          # git pull, зависимости, миграции, restart
```

Скрипт идемпотентен: его можно запускать сколько угодно раз.

## Управление сервисом

```bash
sudo systemctl status warehouse      # состояние
sudo systemctl restart warehouse     # перезапуск
sudo systemctl stop warehouse        # остановка
sudo journalctl -u warehouse -f      # журнал в реальном времени
bash deploy/app/status.sh            # всё сразу
```
