# Управление конфигурацией: инфраструктура как код (Ansible)

**Инфраструктура приводится к требуемому состоянию кодом и автоматически
проверяется после применения.** Машины окружений не настраиваются вручную:

- всё, от пользователей до запуска приложения, описано в `infra/` и
  применяется Ansible;
- повторный запуск ничего не меняет;
- ручная правка управляемого параметра отменяется следующим запуском.

## 1. Средство и структура

Средство — **Ansible**. Причины выбора:

- работает по SSH без агентов на машинах;
- описывает **желаемое состояние**, а не последовательность команд;
- модули идемпотентны.

Версии зафиксированы:

- `infra/requirements.txt` — ansible-core 2.18.1, ansible-lint 24.12.2;
- `infra/requirements.yml` — коллекции ansible.posix 1.6.2 и community.docker 4.1.0.

```
infra/
├── ansible.cfg                  строгая проверка ключей узлов, pipelining
├── known_hosts                  ключи SSH узлов (make infra-known-hosts)
├── bootstrap.yml                первый запуск на чистой машине
├── site.yml                     приведение к требуемому состоянию + проверка
├── verify.yml                   только проверка
├── group_vars/all/common.yml    ОБЩИЕ параметры всех окружений
├── inventories/
│   ├── staging/
│   │   ├── hosts.yml                        узлы окружения
│   │   ├── group_vars/staging/main.yml      параметры ОКРУЖЕНИЯ
│   │   ├── group_vars/staging/vault.yml     СЕКРЕТЫ (зашифрован ansible-vault)
│   │   └── host_vars/warehouse-stage.yml    параметры УЗЛА
│   └── production/  (то же для warehouse-prod)
├── roles/   common, docker, users, ssh, firewall, warehouse, github_runner, verify
└── scripts/ keygen.sh, vault_init.sh, known_hosts.sh, idempotence.sh
```

## 2. Параметры: общие, окружения, узла, секретные

| Уровень | Где | Примеры |
|---|---|---|
| общие | `infra/group_vars/all/common.yml` | лабораторная сеть, пакеты, администраторы и их открытые ключи, учётные записи `ansible` и `deploy`, Docker, адрес репозитория |
| окружения | `inventories/<окр>/group_vars/<окр>/main.yml` | каталог и проект приложения, порт HTTP, уровень журнала, версия выпуска, разрешённые порты firewall, runner, режим проверки |
| узла | `inventories/<окр>/host_vars/<узел>.yml` | IP-адрес, имя машины, адрес публикации Nginx |
| секретные | `inventories/<окр>/group_vars/<окр>/vault.yml` | пароли API и PostgreSQL, пароль sudo администраторов, соль хэша, токен реестра |

**Приоритет** — от общего к частному: параметры окружения перекрывают
общие, параметры узла — параметры окружения. В Ansible так устроен
приоритет переменных: `group_vars/all` рядом с playbook ниже, чем
`group_vars/<группа>` инвентаря, а тот ниже, чем `host_vars`.

**Различия окружений:**

| Параметр | staging | production |
|---|---|---|
| Машина | `warehouse-stage`, 192.168.56.20 | `warehouse-prod`, 192.168.56.30 |
| Порт HTTP | 8080 | 80 |
| Журнал | INFO | WARNING |
| Версия приложения | управляет CD (ЛР6) | задаётся явно: `warehouse_release_tag` |
| GitHub runner | есть (CD и применение инфраструктуры) | нет |
| Проверка выпуска | полный сценарий с тестовыми записями | только чтение, без записей в рабочую базу |
| Секреты | свои | свои, пароль vault другой |

## 3. Роли

| Роль | Что приводит к требуемому состоянию |
|---|---|
| `common` | имя машины, `/etc/hosts`, базовые пакеты; удаляет лишние (`ufw`, `telnet`, `rpcbind`); включает обновления безопасности (шаблон `20auto-upgrades`) |
| `docker` | репозиторий Docker (ключ, `deb822`), Docker Engine и compose, `daemon.json` из шаблона (ротация журналов), служба |
| `users` | администраторы (только ключи, `exclusive`; sudo с паролем из vault); `ansible` (ключ только из лабораторной сети, sudo без пароля из шаблона, проверка `visudo`); `deploy` (без пароля, без входа, единственная группа `docker`) |
| `ssh` | `sshd_config.d/00-warehouse.conf` из шаблона: только ключи, без root, `AllowUsers`, без проброса; проверка `sshd -t` до записи |
| `firewall` | `/etc/nftables.conf` из шаблона (проверка `nft -c`): входящие — только SSH и HTTP из лабораторной сети, остальное drop. Ручные изменения работающих правил обнаруживаются и отменяются |
| `warehouse` | каталоги и права, файл настроек окружения из шаблона (600, секреты из vault). На чистой машине или при новой версии — выпуск через `deploy.sh` из ЛР6. Иначе работающий выпуск поддерживается с текущими настройками (`docker_compose_v2`) |
| `github_runner` | runner нужной версии под `deploy`, регистрация (один раз), служба systemd |
| `verify` | проверка после настройки (раздел 7) |

**Шаблоны** (`roles/*/templates/*.j2`):

- `sshd-warehouse.conf`, `nftables.conf`, `sudoers-ansible`, `daemon.json`;
- `app.env` — настройки приложения;
- `20auto-upgrades`.

Шаблон — единственный источник содержимого файла. Ручная правка отменяется,
а изменение шаблона проходит через merge request.

## 4. Подготовка чистой машины

Исходное состояние — Debian 12 сразу после установки. Нужны:

- пользователь, созданный установщиком, и пароль root;
- адрес в лабораторной сети (`deploy/common/interfaces.example`).

```bash
make infra-setup                         # Ansible в infra/.venv (один раз)
make infra-keygen ENV=production         # ключ ansible окружения → параметры
make vault-init ENV=production           # секреты: случайные, сразу зашифрованы
make infra-known-hosts ENV=production    # ключ SSH машины → infra/known_hosts (сверить отпечаток)
make infra-bootstrap ENV=production USER_NAME=<пользователь установщика>   # пароль пользователя и root
make infra-apply ENV=production TAG=<тег образа>
```

**`bootstrap.yml`** — единственный запуск по паролю. Он ставит Python,
sudo и acl, создаёт учётную запись `ansible` с ключом и sudo. Дальше
`site.yml` работает только от `ansible` по ключу: вход по паролю отключает
роль `ssh`, и машина с этого момента управляется только кодом.

## 5. Повторный запуск без изменений (идемпотентность)

```bash
make infra-apply ENV=staging          # первый раз: changed=N
make infra-idempotence ENV=staging    # повторно: changed=0, иначе ошибка со списком задач
```

Как это обеспечено:

- **модули вместо команд** — `apt`, `user`, `authorized_key`, `template`,
  `service`, `deb822_repository`, `docker_compose_v2` сравнивают текущее
  состояние с требуемым;
- **хэш пароля с постоянной солью** из vault — `user` не меняет пароль при
  каждом запуске;
- **команды с условиями**:
  - `creates:` — runner, выпуск;
  - `changed_when: false` — команды только для чтения;
  - сравнение с эталоном — firewall;
- **кэш APT** обновляется не чаще раза в час (`cache_valid_time`);
- **приложение** пересоздаётся, только если изменились его настройки. Разовый
  `migrate` не перезапускается: `services` без `migrate`, `dependencies: false`.

## 6. Восстановление вручную изменённой конфигурации

| Ручное изменение на машине | Что делает Ansible |
|---|---|
| `PasswordAuthentication yes` в `/etc/ssh/sshd_config.d/00-warehouse.conf` | шаблон возвращает `no`, SSH перезапускается |
| `nft add rule inet warehouse input tcp dport 5432 accept` | работающие правила отличаются от эталона → правила загружаются заново, порт закрыт |
| `chmod 644 /opt/warehouse-stage/env/stage.env` | права снова 600 |
| `usermod -aG sudo deploy` | `deploy` снова только в группе `docker` |
| новый ключ в `~ansible/.ssh/authorized_keys` | удалён (`exclusive: true`) |
| `systemctl stop docker` | Docker запущен, контейнеры приложения подняты |
| `LOG_LEVEL=DEBUG` в `stage.env` | шаблон восстанавливает значение, контейнеры пересоздаются с ним |

Порядок показа:

1. `make infra-check` — `--check --diff` показывает, что изменено вручную;
2. `make infra-apply` — восстанавливает;
3. `make infra-idempotence` — снова `changed=0`.

## 7. Проверка доступности после настройки

Роль `verify` выполняется в конце `site.yml` и отдельно — `make infra-verify`:

1. `/healthz` отвечает через Nginx (ожидание до 60 с);
2. `/readyz` — база данных доступна;
3. `/version` — работает коммит, записанный в состоянии выпуска;
4. основной сценарий (`scripts/smoke_test.sh`): в staging — полный, с
   записями; в production — только чтение;
5. **лишних портов нет** — на внешних адресах слушают только SSH и HTTP
   приложения (`ss -tln`), остальное — только на loopback;
6. **права**:
   - файл настроек окружения — 600, владелец `deploy`;
   - `deploy` состоит только в группе `docker`.

Любое расхождение — ошибка, и настройка не считается выполненной.

## 8. Секреты

- **Шифрование.** `vault.yml` каждого окружения зашифрован `ansible-vault`
  (AES-256). Пароли vault у окружений разные. В репозитории лежат только
  зашифрованные файлы и шаблоны `vault.yml.example`.
- **Создание.** `make vault-init ENV=…` генерирует случайные значения и
  шифрует их сразу; открытый файл существует только во временном каталоге.
  Изменение — `make vault-edit`, просмотр — `make vault-view`.
- **Пароли vault и ключи `ansible` хранятся вне репозитория:**
  - на управляющей машине — `~/.config/warehouse/vault-<окр>.pass` и
    `~/.ssh/warehouse_ansible_<окр>`, права 600;
  - в CI — секреты окружений `infra-staging` и `infra-production`;
    задание записывает их во временные файлы и удаляет в конце.
- **Защита от утечек:**
  - `make policy` проверяет, что каждый `vault.yml` начинается с
    `$ANSIBLE_VAULT;1.`, и что пароли подключения не заданы открытым текстом;
  - `.gitignore` исключает `*.pass` и ключи;
  - gitleaks (ЛР5) ищет секреты по всей истории.
- **В журналах секретов нет:**
  - шаблон с паролями применяется с `diff: false`;
  - задачи с паролями — `no_log: true`.

## 9. Pipeline инфраструктуры

| Pipeline | Когда | Что делает |
|---|---|---|
| `Infrastructure CI` (`infra-ci.yml`) | каждый push и merge request с изменениями `infra/` | `make infra-setup`, `make infra-lint`: ansible-lint (профиль production), syntax-check обоих окружений, требования проекта |
| `Infrastructure apply` (`infra-apply.yml`) | после успешного Infrastructure CI на `main` (staging) или вручную (staging / production, check / apply) | **ждёт подтверждения**, затем `make infra-check`, `make infra-apply`, `make infra-idempotence`, `make infra-verify` |

**Условия применения:**

- выполняется на self-hosted runner лабораторной сети, только из `main`;
- **только после подтверждения** — Required reviewers окружений
  `infra-staging` и `infra-production`;
- одновременно с развёртыванием того же окружения не запускается: общая
  группа `concurrency` с `deploy.yml`.

## 10. Требования к инфраструктурному коду

| Требование | Как обеспечено | Как проверяется |
|---|---|---|
| **Нет лишних портов** | firewall из шаблона — только `firewall_allow`; Nginx публикуется только на адресе лабораторной сети; лишние сетевые пакеты удаляются | `check_infra.py`: в `firewall_allow` только SSH и HTTP; роль firewall: `assert`; роль verify: `ss -tln` |
| **Минимальные права** | `deploy` — только группа `docker`, без пароля, без SSH; `ansible` — вход по ключу только из лабораторной сети, без проброса; администраторы — sudo с паролем; файлы — явные права (`0600` для секретов, `0440` для sudoers) | ansible-lint `risky-file-permissions`; роль verify: права и группы |
| **Нет необъяснимых shell-команд** | `shell` и `script` запрещены. `command`/`raw` — только с `argv` и комментарием `# Обоснование:`, если команда что-то меняет; иначе `changed_when: false` | `check_infra.py`; ansible-lint `no-changed-when`, `command-instead-of-module`, `no-free-form` |
| **Повторяемость результата** | точные версии Ansible и коллекций; идемпотентные модули; ключи узлов закреплены (`known_hosts`, `StrictHostKeyChecking=yes`) | `make infra-idempotence` (`changed=0`) в pipeline после каждого применения |

## 11. Защита критических ролей, шаблонов и секретов

- `/infra/` в `.github/CODEOWNERS` (`scripts/setup_infra.sh`): изменения
  ролей, шаблонов, параметров окружений и `vault.yml` нельзя влить в `main`
  без одобрения владельца.
- `make infra-lint` не пройдёт, если у `/infra/` нет владельцев.
- Применение к окружениям — только после подтверждения в GitHub (раздел 9).
- `.ansible-lint`, `scripts/check_infra.py` и pipeline — тоже критические
  файлы: ослабить проверку незаметно нельзя.
