# Лабораторная работа №7 — что сделано и что показывать на защите

Результат: **инфраструктура приводится к требуемому состоянию кодом и
автоматически проверяется после применения.** Подробности — [`infra.md`](infra.md).

## Соответствие заданию

| № | Требование | Где реализовано |
|---|---|---|
| 1 | Средство управления конфигурацией | Ansible: ansible-core 2.18.1, коллекции ansible.posix и community.docker точных версий (`infra/requirements*.txt/yml`) |
| 2 | Целевые узлы; параметры общие, окружения, узла, секретные | `inventories/<окр>/hosts.yml`; `group_vars/all/common.yml`, `inventories/<окр>/group_vars/<окр>/main.yml`, `host_vars/<узел>.yml`, `vault.yml` |
| 3 | Подготовка чистой Linux-машины | `bootstrap.yml` (единственный вход по паролю) → `site.yml` |
| 4 | Пользователи, SSH, пакеты, Docker, каталоги и права, firewall, конфигурация и запуск сервисов | роли `users`, `ssh`, `common`, `docker`, `warehouse`, `firewall`, `github_runner` |
| 5 | Шаблоны конфигурационных файлов | `roles/*/templates/*.j2`: sshd, nftables, sudoers, daemon.json, настройки приложения, обновления безопасности |
| 6 | Не менее двух окружений | `staging` (192.168.56.20) и `production` (192.168.56.30): порт, журнал, runner, режим проверки, способ выбора версии, свои секреты |
| 7 | Повторный запуск без необоснованных изменений | идемпотентные модули; `make infra-idempotence` требует `changed=0` |
| 8 | Ручное изменение и восстановление | шаблоны, `exclusive`-ключи, точные группы, сверка правил nftables с эталоном (раздел 6 `infra.md`) |
| 9 | Нет незашифрованных секретов в репозитории | `ansible-vault` (`make vault-init`); `make policy` проверяет заголовок `$ANSIBLE_VAULT`; пароли vault и ключи — вне репозитория |
| 10 | Проверка доступности приложения после настройки | роль `verify`: `/healthz`, `/readyz`, `/version`, основной сценарий, порты, права |
| 11 | Отдельный pipeline | `Infrastructure CI` (проверки) и `Infrastructure apply` (применение с подтверждением, идемпотентность, проверка) |
| 12 | Требования к инфраструктурному коду | `infra.md`, раздел 10; ansible-lint (production) + `scripts/check_infra.py` + роль `verify` |
| 13 | Обязательное согласование критических ролей, шаблонов и секретов | `/infra/` в CODEOWNERS; Required reviewers окружений `infra-staging`/`infra-production` |

## Подготовка (один раз)

```bash
git switch -c feature/16-infrastructure-as-code     # от main после ЛР6
git am ~/lab7-iac/patches/lab7/*.patch

make infra-setup                                    # Ansible в infra/.venv
make infra-keygen ENV=staging && make infra-keygen ENV=production

# секреты; для staging — сохранить пароли уже работающего окружения:
ssh deployer@192.168.56.20 'sudo cat /opt/warehouse-stage/env/stage.env' > /tmp/stage.env
FROM_ENV_FILE=/tmp/stage.env make vault-init ENV=staging && rm /tmp/stage.env
make vault-init ENV=production

make infra-known-hosts ENV=staging && make infra-known-hosts ENV=production
./scripts/setup_infra.sh --approve <ваш-логин> --approve <логин-Садыкова>
make infra-lint
git add infra .github/CODEOWNERS && git commit -m "chore: ключи, секреты и владельцы инфраструктуры"
```

Если вход `deployer` на staging по паролю sudo не настроен, `sudo cat`
не сработает. Тогда скопируйте `stage.env` через консоль ВМ или создайте
staging с нуля, как production.

## Что показывать на защите

**1. Подготовка чистой машины** — новая ВМ Debian 12 `warehouse-prod`,
192.168.56.30, сразу после установки:

```bash
make infra-bootstrap ENV=production USER_NAME=<пользователь установщика>  # пароль пользователя и root
make infra-apply ENV=production TAG=<тег образа, прошедшего staging>
```

В выводе видны роли по порядку и `changed` на каждом шаге. В конце —
проверки роли `verify`:

```
ok: Работает версия 0.10.0, коммит …
ok: Снаружи слушают порты: 22, 80
ok: deploy: группы deploy docker
```

Потом `http://192.168.56.30/docs` в браузере.

**2. Повторный запуск без необоснованных изменений**

```bash
make infra-idempotence ENV=production
# PLAY RECAP: warehouse-prod : ok=… changed=0 … failed=0
# Повторный запуск: changed=0 — состояние уже соответствует коду.
```

**3. Восстановление вручную изменённой конфигурации** — на машине
(`ssh deployer@192.168.56.30`):

```bash
sudo sed -i 's/^PasswordAuthentication no/PasswordAuthentication yes/' /etc/ssh/sshd_config.d/00-warehouse.conf
sudo nft add rule inet warehouse input tcp dport 5432 accept
sudo chmod 644 /opt/warehouse-prod/env/prod.env
sudo usermod -aG sudo deploy
```

Затем в WSL:

```bash
make infra-check ENV=production        # --diff: PasswordAuthentication yes → no, mode 0644 → 0600, …
make infra-apply ENV=production        # changed: шаблон SSH, «Восстановить правила…», права, группы
make infra-idempotence ENV=production  # снова changed=0
```

Проверка на машине:

- `sudo nft list table inet warehouse` — порта 5432 нет;
- `id deploy` — только группа docker.

**4. Проверка доступности приложения после настройки**

```bash
make infra-verify ENV=production       # /healthz, /readyz, /version, сценарий только чтения, порты, права
make infra-verify ENV=staging          # в staging — полный сценарий с записями
```

Для сравнения можно остановить приложение
(`sudo -u deploy docker compose -p warehouse-prod stop nginx`) и запустить
`make infra-verify`: проверка упадёт на `/healthz`. После этого
`make infra-apply` поднимет Nginx снова.

**5. Отсутствие открытых секретов**

```bash
head -1 infra/inventories/*/group_vars/*/vault.yml   # $ANSIBLE_VAULT;1.2;AES256;staging / production
git ls-files | grep -E '\.pass$|warehouse_ansible' || echo "паролей vault и ключей в репозитории нет"
make secrets-scan                                     # gitleaks по всей истории: no leaks found
make policy                                           # в т. ч. проверка шифрования vault.yml
```

На сервере секреты есть только в файле настроек окружения. Права 600,
владелец `deploy`: `sudo ls -l /opt/warehouse-prod/env/`.

**Pipeline** — Actions → **Infrastructure apply** → Run workflow →
`production`, `check`:

1. окружение `infra-production` ждёт **Approve**;
2. после подтверждения — `--check --diff` без изменений;
3. режим `apply` дополнительно выполняет идемпотентность и проверку.

## Возможные вопросы

- **Почему nftables, а не ufw, как в ЛР2?** Файл `nftables.conf` целиком
  задаётся шаблоном, поэтому состояние декларативное. У ufw правила
  накапливаются командами, и лишнее правило, добавленное вручную, модуль
  Ansible не удалит. Своя таблица `inet warehouse` не трогает правила Docker.
- **Как Ansible замечает ручное `nft add rule`?** Файл при этом не меняется.
  Поэтому роль сравнивает работающие правила с эталоном, снятым после
  загрузки, и при расхождении загружает файл заново.
- **Почему у `ansible` sudo без пароля?** Применение конфигурации требует
  root. Права ограничены входом: только по ключу, только из лабораторной
  сети, без проброса портов и агента. Каждое применение из pipeline
  подтверждает человек.
- **Чем отличаются окружения?** Только параметрами (`infra.md`, раздел 2).
  Роли и шаблоны одни и те же.
