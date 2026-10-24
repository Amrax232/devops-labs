"""Статическая проверка контейнерной конфигурации (ЛР4): make container-lint.

Проверяет Dockerfile, .dockerignore и docker-compose*.yml, не запуская
контейнеров, поэтому входит в make verify. Запрещено:

  - образы с тегом latest или без тега;
  - запуск приложения от root;
  - секреты в образе: ENV/ARG с паролями и ключами, .env в контексте сборки;
  - отключённый или отсутствующий healthcheck у долгоживущих сервисов;
  - лишние опубликованные порты: наружу публикуется только nginx, порт БД —
    только в docker-compose.dev.yml и только на 127.0.0.1;
  - privileged и network_mode: host.

Обязательно: ограничения ресурсов у всех сервисов, внутренние сети у БД и
приложения, именованный том БД, CMD в exec-форме, init у приложения,
порядок запуска (db healthy → migrate → app → nginx), requirements.lock.

Конфигурация compose читается через `docker compose config` — так проверяется
ровно то, что будет запущено (с учётом якорей и подстановки переменных).
Демону Docker работать не нужно.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import shutil
import subprocess  # nosec B404 - вызывается только docker compose config с фиксированными аргументами
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PUBLIC_SERVICES = {"nginx"}  # единственный сервис, которому разрешено публиковать порты
APP_SERVICES = {"app1", "app2"}  # экземпляры приложения за балансировщиком
DB_SERVICE = "db"
DB_DATA_PATH = "/var/lib/postgresql/data"
MIN_APP_INSTANCES = 2

SECRET_NAME_RE = re.compile(r"PASSWORD|PASSWD|SECRET|TOKEN|API_?KEY|PRIVATE_?KEY", re.I)
ROOT_USERS = {"", "root", "0", "0:0", "root:root"}

# Пути, которые не должны попадать в контекст сборки (а значит, и в образ)
MUST_BE_IGNORED = [
    ".env",
    "deploy/app/warehouse.env",
    ".git/config",
    ".venv/bin/python",
    "backups/warehouse-20260101-000000.dump",
    "reports/coverage.xml",
    "tests/conftest.py",
]
MUST_BE_INCLUDED = ["app/main.py", "migrations/env.py", "alembic.ini", "requirements.lock"]

# Значения-заглушки: проверка не зависит от .env и не видит настоящих паролей
PLACEHOLDER_ENV = {
    "AUTH_PASSWORD": "container-lint-placeholder",
    "POSTGRES_PASSWORD": "container-lint-placeholder",
    "REGISTRY_IMAGE": "ghcr.io/container-lint/warehouse-inventory",
    "IMAGE_TAG": "0123456789abcdef0123456789abcdef01234567",
}


# ------------------------------------------------------------------ образы
def image_problems(image: str | None, where: str) -> list[str]:
    if not image:
        return [f"{where}: образ не указан"]
    if "@sha256:" in image:
        return []
    name_part = image.rsplit("/", 1)[-1]
    if ":" not in name_part:
        return [f"{where}: образ «{image}» без тега (это тот же latest)"]
    tag = name_part.split(":", 1)[1]
    if tag == "latest":
        return [f"{where}: образ «{image}» с тегом latest — сборка невоспроизводима"]
    if "$" in tag:
        return [f"{where}: тег образа «{image}» не раскрыт"]
    return []


# -------------------------------------------------------------- Dockerfile
def dockerfile_instructions(text: str) -> list[tuple[str, str]]:
    """Инструкции Dockerfile с учётом переносов строк и комментариев."""
    lines: list[str] = []
    current = ""
    for raw in text.splitlines():
        stripped = raw.strip()
        if not current and (not stripped or stripped.startswith("#")):
            continue
        if current and stripped.startswith("#"):
            continue
        if stripped.endswith("\\"):
            current += stripped[:-1] + " "
            continue
        current += stripped
        lines.append(current)
        current = ""
    if current:
        lines.append(current)
    result = []
    for line in lines:
        keyword, _, rest = line.partition(" ")
        result.append((keyword.upper(), rest.strip()))
    return result


def _substitute(value: str, args: dict[str, str]) -> str:
    def repl(match: re.Match[str]) -> str:
        name = match.group(1) or match.group(2)
        return args.get(name, match.group(0))

    return re.sub(r"\$\{(\w+)\}|\$(\w+)", repl, value)


def _keys(rest: str) -> list[str]:
    """Имена переменных из ENV/ARG (формы KEY=VALUE ... и KEY VALUE)."""
    if "=" not in rest.split(" ", 1)[0]:
        return [rest.split(" ", 1)[0]]
    return [part.split("=", 1)[0] for part in re.findall(r"(\w+=\"[^\"]*\"|\w+=\S*)", rest)]


def check_dockerfile(path: Path) -> list[str]:
    if not path.exists():
        return ["нет Dockerfile"]
    problems: list[str] = []
    instructions = dockerfile_instructions(path.read_text(encoding="utf-8"))
    global_args: dict[str, str] = {}
    stages: list[str] = []
    final: list[tuple[str, str]] = []

    for keyword, rest in instructions:
        if keyword == "ARG" and not stages and "=" in rest:
            name, value = rest.split("=", 1)
            global_args[name.strip()] = value.strip().strip('"')
        if keyword == "FROM":
            parts = rest.split()
            image = _substitute(parts[0], global_args)
            if image not in stages and image != "scratch":
                problems += image_problems(image, "Dockerfile FROM")
            stages.append(parts[2] if len(parts) >= 3 and parts[1].upper() == "AS" else image)
            final = []
            continue
        final.append((keyword, rest))
        if keyword in {"ENV", "ARG"}:
            for key in _keys(rest):
                if SECRET_NAME_RE.search(key):
                    problems.append(f"Dockerfile {keyword} {key}: секреты в образе запрещены")

    if not stages:
        return problems + ["Dockerfile без FROM"]

    users = [rest for keyword, rest in final if keyword == "USER"]
    if not users:
        problems.append("Dockerfile: в итоговом этапе нет USER — процесс запустится от root")
    elif users[-1].strip() in ROOT_USERS or users[-1].split(":")[0] in {"root", "0"}:
        problems.append(f"Dockerfile: USER {users[-1]} — запуск от root запрещён")

    healthchecks = [rest for keyword, rest in final if keyword == "HEALTHCHECK"]
    if not healthchecks:
        problems.append("Dockerfile: нет HEALTHCHECK")
    elif healthchecks[-1].upper().startswith("NONE"):
        problems.append("Dockerfile: HEALTHCHECK NONE — отключать проверку запрещено")

    commands = [rest for keyword, rest in final if keyword in {"CMD", "ENTRYPOINT"}]
    if not commands:
        problems.append("Dockerfile: нет CMD/ENTRYPOINT")
    elif not commands[-1].startswith("["):
        problems.append(
            "Dockerfile: CMD в shell-форме — sh не передаёт SIGTERM приложению, "
            'нужна exec-форма ["..."]'
        )

    copied = " ".join(rest for keyword, rest in instructions if keyword == "COPY")
    if "requirements.lock" not in copied:
        problems.append("Dockerfile: зависимости ставятся без requirements.lock")
    if not (ROOT / "requirements.lock").exists():
        problems.append("нет requirements.lock: выполните make lock и закоммитьте файл")
    return problems


# ------------------------------------------------------------ .dockerignore
def is_ignored(path: str, rules: list[str]) -> bool:
    """Упрощённая модель .dockerignore: правило применяется к пути и к каждому
    его каталогу-предку, побеждает последнее подходящее правило."""
    parts = path.split("/")
    prefixes = ["/".join(parts[: i + 1]) for i in range(len(parts))]
    ignored = False
    for rule in rules:
        negate = rule.startswith("!")
        pattern = rule[1:] if negate else rule
        pattern = pattern.strip("/")
        variants = {pattern}
        if pattern.startswith("**/"):
            variants.add(pattern[3:])
        if any(fnmatch.fnmatchcase(p, v) for p in prefixes for v in variants):
            ignored = not negate
    return ignored


def check_dockerignore(path: Path) -> list[str]:
    if not path.exists():
        return ["нет .dockerignore — в контекст сборки попадут .env, .git и резервные копии"]
    rules = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    problems = [
        f".dockerignore: «{item}» попадёт в контекст сборки"
        for item in MUST_BE_IGNORED
        if not is_ignored(item, rules)
    ]
    problems += [
        f".dockerignore: «{item}» исключён, но нужен для сборки"
        for item in MUST_BE_INCLUDED
        if is_ignored(item, rules)
    ]
    return problems


# ------------------------------------------------------------------ compose
def compose_config(*files: str) -> dict:
    docker = shutil.which("docker")
    if docker is None:
        raise SystemExit("docker не найден: проверка compose невозможна")
    command = [docker, "compose"]
    for file in files:
        command += ["-f", file]
    command += ["config", "--format", "json"]
    env = {**os.environ, **PLACEHOLDER_ENV}
    result = subprocess.run(  # nosec B603 - аргументы фиксированы, оболочка не используется
        command, cwd=ROOT, env=env, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise SystemExit(f"docker compose config: {result.stderr.strip()}")
    return json.loads(result.stdout)


def _limits(service: dict) -> dict:
    return service.get("deploy", {}).get("resources", {}).get("limits", {}) or {}


def check_service(name: str, service: dict, networks: dict) -> list[str]:
    where = f"compose: сервис {name}"
    problems = image_problems(service.get("image"), where)
    one_shot = service.get("restart", "no") == "no"

    if service.get("privileged"):
        problems.append(f"{where}: privileged запрещён")
    if service.get("network_mode") == "host":
        problems.append(f"{where}: network_mode host запрещён")
    user = str(service.get("user", "")).strip()
    if "user" in service and (user in ROOT_USERS or user.split(":")[0] in {"root", "0"}):
        problems.append(f"{where}: user {user!r} — запуск от root запрещён")

    healthcheck = service.get("healthcheck") or {}
    if healthcheck.get("disable") or (healthcheck.get("test") or [""])[0] == "NONE":
        problems.append(f"{where}: healthcheck отключён")
    elif not one_shot and not healthcheck.get("test"):
        problems.append(f"{where}: нет healthcheck")

    limits = _limits(service)
    for key in ("cpus", "memory", "pids"):
        if not limits.get(key):
            problems.append(f"{where}: не задано ограничение ресурсов {key}")

    if service.get("ports") and name not in PUBLIC_SERVICES:
        problems.append(f"{where}: публикует порты — наружу открыт только {PUBLIC_SERVICES}")
    for port in service.get("ports") or []:
        if not port.get("host_ip"):
            problems.append(f"{where}: порт {port.get('published')} открыт на всех интерфейсах")

    if name in APP_SERVICES or name == DB_SERVICE:
        for net in service.get("networks") or {}:
            if not networks.get(net, {}).get("internal"):
                problems.append(f"{where}: сеть {net} не внутренняя (internal: true)")

    if name in APP_SERVICES:
        if not service.get("init"):
            problems.append(f"{where}: нет init: true — сигналы и зомби-процессы")
        if not service.get("read_only"):
            problems.append(f"{where}: корневая ФС не read_only")
        depends = service.get("depends_on") or {}
        if depends.get(DB_SERVICE, {}).get("condition") != "service_healthy":
            problems.append(f"{where}: запуск не ждёт готовности БД (service_healthy)")
        if depends.get("migrate", {}).get("condition") != "service_completed_successfully":
            problems.append(f"{where}: запуск не ждёт успешных миграций")
        env = service.get("environment") or {}
        if not env.get("INSTANCE_ID"):
            problems.append(f"{where}: не задан INSTANCE_ID")
    return problems


def check_compose() -> list[str]:
    config = compose_config("docker-compose.yml")
    services = config.get("services", {})
    networks = config.get("networks", {})
    problems: list[str] = []
    for name, service in sorted(services.items()):
        problems += check_service(name, service, networks)

    present_apps = APP_SERVICES & services.keys()
    if len(present_apps) < MIN_APP_INSTANCES:
        problems.append(f"compose: экземпляров приложения меньше {MIN_APP_INSTANCES}")
    if not PUBLIC_SERVICES <= services.keys():
        problems.append("compose: нет сервиса nginx — единственной точки входа")
    else:
        depends = services["nginx"].get("depends_on") or {}
        for app in sorted(present_apps):
            if depends.get(app, {}).get("condition") != "service_healthy":
                problems.append(f"compose: nginx не ждёт готовности {app}")

    db = services.get(DB_SERVICE, {})
    volumes = [v for v in db.get("volumes") or [] if v.get("target") == DB_DATA_PATH]
    if not volumes or volumes[0].get("type") != "volume":
        problems.append(f"compose: данные БД ({DB_DATA_PATH}) не в именованном томе")

    dev = compose_config("docker-compose.yml", "docker-compose.dev.yml")
    for port in dev["services"].get(DB_SERVICE, {}).get("ports") or []:
        if port.get("host_ip") != "127.0.0.1":
            problems.append("docker-compose.dev.yml: порт БД открыт не только на 127.0.0.1")
    for name in sorted(set(dev["services"]) - {DB_SERVICE}):
        if dev["services"][name].get("ports") != services.get(name, {}).get("ports"):
            problems.append(f"docker-compose.dev.yml: меняет порты сервиса {name}")

    # развёртывание (ЛР6): образ приложения только из реестра, без сборки на сервере
    deploy_file = ROOT / "docker-compose.deploy.yml"
    if deploy_file.exists():
        deployed = compose_config("docker-compose.yml", "docker-compose.deploy.yml")["services"]
        expected = f"{PLACEHOLDER_ENV['REGISTRY_IMAGE']}:{PLACEHOLDER_ENV['IMAGE_TAG']}"
        for name in sorted(APP_SERVICES | {"migrate"}):
            service = deployed.get(name, {})
            if service.get("build"):
                problems.append(f"docker-compose.deploy.yml: {name} собирается на сервере")
            if service.get("image") != expected:
                problems.append(f"docker-compose.deploy.yml: {name} не из реестра по IMAGE_TAG")
            if service.get("pull_policy") != "never":
                problems.append(f"docker-compose.deploy.yml: {name} без pull_policy: never")
    return problems


def main() -> int:
    problems = (
        check_dockerfile(ROOT / "Dockerfile")
        + check_dockerignore(ROOT / ".dockerignore")
        + check_compose()
    )
    if problems:
        print("Нарушения требований к контейнерам (docs/containers.md):")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("Контейнерная конфигурация соответствует требованиям.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
