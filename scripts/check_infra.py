"""Требования к инфраструктурному коду (ЛР7): входит в make policy и make infra-lint.

Дополняет ansible-lint (профиль production) правилами проекта:

  - секреты только зашифрованные: каждый vault.yml начинается с $ANSIBLE_VAULT,
    пароли подключения и sudo не задаются открытым текстом;
  - нет необъяснимых команд: shell запрещён; command и raw — только с
    комментарием «# Обоснование:», кроме команд только для чтения
    (changed_when: false); у изменяющих команд — creates/removes/changed_when;
  - нет лишних портов: в firewall_allow только SSH и HTTP приложения;
  - строгая проверка ключей узлов: StrictHostKeyChecking=yes, known_hosts в репозитории;
  - заглушки (CHANGE_ME) в ключах и адресах не остаются.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
INFRA = ROOT / "infra"

COMMAND_MODULES = {
    "ansible.builtin.command",
    "ansible.builtin.raw",
    "command",
    "raw",
}
FORBIDDEN_MODULES = {"ansible.builtin.shell", "shell", "ansible.builtin.script", "script"}
PLAINTEXT_SECRET_KEYS = {
    "ansible_password",
    "ansible_ssh_pass",
    "ansible_become_password",
    "ansible_become_pass",
}
ALLOWED_FIREWALL_PORTS = {"{{ ssh_port }}", "{{ warehouse_http_port }}"}
JUSTIFICATION = "# Обоснование:"
PLACEHOLDER = "CHANGE_ME"


def _tasks(node: yaml.Node) -> list[yaml.MappingNode]:
    """Все задачи файла (включая вложенные в block/rescue/always/tasks)."""
    found: list[yaml.MappingNode] = []
    if isinstance(node, yaml.SequenceNode):
        for item in node.value:
            found += _tasks(item)
    elif isinstance(node, yaml.MappingNode):
        keys = {key.value for key, _ in node.value if isinstance(key, yaml.ScalarNode)}
        if keys & (COMMAND_MODULES | FORBIDDEN_MODULES | {"name"}):
            found.append(node)
        for key, value in node.value:
            if key.value in {
                "block",
                "rescue",
                "always",
                "tasks",
                "pre_tasks",
                "post_tasks",
                "handlers",
            }:
                found += _tasks(value)
    return found


def _value(task: yaml.MappingNode, name: str) -> yaml.Node | None:
    for key, value in task.value:
        if key.value == name:
            return value
    return None


def check_commands() -> list[str]:
    problems: list[str] = []
    files = sorted(INFRA.glob("*.yml")) + sorted(INFRA.glob("roles/*/*/*.yml"))
    for path in files:
        if "/collections/" in path.as_posix() or path.name == "requirements.yml":
            continue
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        root = yaml.compose(text)
        if root is None:
            continue
        for task in _tasks(root):
            keys = {key.value for key, _ in task.value}
            line = task.start_mark.line + 1
            if keys & FORBIDDEN_MODULES:
                problems.append(f"{rel}:{line}: shell/script запрещены — нужен command с argv")
                continue
            module = keys & COMMAND_MODULES
            if not module:
                continue
            changed = _value(task, "changed_when")
            read_only = changed is not None and changed.value in ("false", "False")
            args = _value(task, next(iter(module)))
            has_guard = isinstance(args, yaml.MappingNode) and {
                key.value for key, _ in args.value
            } & {"creates", "removes"}
            if changed is None and not has_guard:
                problems.append(f"{rel}:{line}: команда без changed_when/creates/removes")
            body = "\n".join(lines[task.start_mark.line : task.end_mark.line])
            if not read_only and JUSTIFICATION not in body:
                problems.append(f"{rel}:{line}: изменяющая команда без «{JUSTIFICATION}»")
    return problems


def check_secrets() -> list[str]:
    problems: list[str] = []
    for vault in sorted(INFRA.glob("inventories/*/group_vars/*/vault.yml")):
        first = vault.read_text(encoding="utf-8", errors="replace").split("\n", 1)[0]
        if not first.startswith("$ANSIBLE_VAULT;1."):
            problems.append(f"{vault.relative_to(ROOT)}: секреты не зашифрованы (ansible-vault)")
    for path in sorted(INFRA.glob("**/*.yml")):
        if "/collections/" in path.as_posix() or path.name.startswith("vault.yml"):
            continue
        text = path.read_text(encoding="utf-8")
        for key in PLAINTEXT_SECRET_KEYS:
            if re.search(rf"^\s*{key}\s*:", text, re.M):
                problems.append(f"{path.relative_to(ROOT)}: {key} открытым текстом")
    return problems


def check_firewall() -> list[str]:
    problems: list[str] = []
    for env_vars in sorted(INFRA.glob("inventories/*/group_vars/*/main.yml")):
        data = yaml.safe_load(env_vars.read_text(encoding="utf-8")) or {}
        rules = data.get("firewall_allow") or []
        if not rules:
            problems.append(f"{env_vars.relative_to(ROOT)}: не задан firewall_allow")
        for rule in rules:
            if str(rule.get("port")) not in ALLOWED_FIREWALL_PORTS:
                where = env_vars.relative_to(ROOT)
                problems.append(f"{where}: лишний порт в firewall_allow: {rule.get('port')}")
    return problems


def check_ssh_and_placeholders() -> list[str]:
    problems: list[str] = []
    cfg = (INFRA / "ansible.cfg").read_text(encoding="utf-8")
    if "StrictHostKeyChecking=yes" not in cfg or re.search(r"host_key_checking\s*=\s*False", cfg):
        problems.append("infra/ansible.cfg: проверка ключей узлов ослаблена")
    if not (INFRA / "known_hosts").exists():
        problems.append("нет infra/known_hosts: выполните make infra-known-hosts ENV=<окружение>")
    env_files = sorted(INFRA.glob("inventories/*/group_vars/*/main.yml"))
    for path in [INFRA / "group_vars/all/common.yml", *env_files]:
        if PLACEHOLDER in path.read_text(encoding="utf-8"):
            problems.append(
                f"{path.relative_to(ROOT)}: заглушки {PLACEHOLDER} — выполните "
                "infra/scripts/keygen.sh и укажите владельца репозитория"
            )
    return problems


def check_codeowners() -> list[str]:
    """Роли, шаблоны и секретные настройки меняются только с одобрением владельца."""
    codeowners = ROOT / ".github" / "CODEOWNERS"
    lines = codeowners.read_text(encoding="utf-8").splitlines() if codeowners.exists() else []
    owned = any(
        line.split()[0] in {"/infra/", "/infra/**"} and len(line.split()) > 1
        for line in lines
        if line.strip() and not line.startswith("#")
    )
    return [] if owned else ["нет владельцев /infra/ в .github/CODEOWNERS: scripts/setup_infra.sh"]


def problems(strict: bool = True) -> list[str]:
    """strict=False — без проверок полноты настройки окружений (для make policy)."""
    if not INFRA.exists():
        return []
    found = check_commands() + check_secrets() + check_firewall()
    if strict:
        found += check_ssh_and_placeholders() + check_codeowners()
    return found


def main() -> int:
    found = problems()
    if found:
        print("Нарушения требований к инфраструктурному коду (docs/infra.md):")
        for problem in found:
            print(f"  - {problem}")
        return 1
    print("Инфраструктурный код соответствует требованиям.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
