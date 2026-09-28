#!/usr/bin/env bash
# Базовая настройка машины: выполняется на ОБЕИХ виртуальных машинах.
#
# Что делает:
#   - обновляет пакеты и ставит минимальный набор утилит;
#   - задаёт имя машины и записи в /etc/hosts;
#   - создаёт администратора deployer (sudo, вход только по ключу);
#   - запрещает вход root по SSH и аутентификацию по паролю.
#
# Запуск (от root):  bash 00-base-setup.sh app|db
set -euo pipefail

ROLE="${1:-}"
if [[ "$ROLE" != "app" && "$ROLE" != "db" ]]; then
    echo "Использование: $0 app|db" >&2
    exit 1
fi

APP_IP="${APP_IP:-192.168.56.10}"
DB_IP="${DB_IP:-192.168.56.11}"
ADMIN_USER="${ADMIN_USER:-deployer}"

if [[ $EUID -ne 0 ]]; then
    echo "Скрипт нужно запускать от root" >&2
    exit 1
fi

echo "==> 1/5 обновление системы и базовые пакеты"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq sudo ufw curl ca-certificates gnupg vim less git

echo "==> 2/5 имя машины и /etc/hosts"
hostnamectl set-hostname "warehouse-${ROLE}"
grep -q "$APP_IP" /etc/hosts || echo "$APP_IP  warehouse-app" >> /etc/hosts
grep -q "$DB_IP" /etc/hosts || echo "$DB_IP  warehouse-db" >> /etc/hosts

echo "==> 3/5 администратор $ADMIN_USER"
if ! id "$ADMIN_USER" >/dev/null 2>&1; then
    adduser --disabled-password --gecos "Infrastructure admin" "$ADMIN_USER"
    usermod -aG sudo "$ADMIN_USER"
    echo "Пользователь $ADMIN_USER создан. Пароль не задан: вход только по ключу."
fi
install -d -m 700 -o "$ADMIN_USER" -g "$ADMIN_USER" "/home/$ADMIN_USER/.ssh"
touch "/home/$ADMIN_USER/.ssh/authorized_keys"
chown "$ADMIN_USER:$ADMIN_USER" "/home/$ADMIN_USER/.ssh/authorized_keys"
chmod 600 "/home/$ADMIN_USER/.ssh/authorized_keys"

echo "==> 4/5 настройка SSH"
install -d -m 755 /etc/ssh/sshd_config.d
sed "s/__ADMIN_USER__/$ADMIN_USER/" "$(dirname "$0")/ssh-hardening.conf" \
    > /etc/ssh/sshd_config.d/10-hardening.conf
chmod 644 /etc/ssh/sshd_config.d/10-hardening.conf
sshd -t
echo "Проверка конфигурации SSH пройдена."

echo "==> 5/5 базовые правила firewall"
ufw --force reset >/dev/null
ufw default deny incoming
ufw default allow outgoing
ufw allow from 192.168.56.0/24 to any port 22 proto tcp comment "SSH из лабораторной сети"

cat <<MSG

Готово. Дальше:
  1. С рабочей машины скопируйте открытый ключ:
       ssh-copy-id -i ~/.ssh/warehouse.pub $ADMIN_USER@<ip этой машины>
     или вручную добавьте его в /home/$ADMIN_USER/.ssh/authorized_keys
  2. УБЕДИТЕСЬ, что вход по ключу работает, и только потом примените новые
     правила SSH и firewall:
       systemctl restart ssh
       ufw --force enable
  Порядок важен: если перезапустить SSH до добавления ключа, доступ к машине
  останется только через консоль VirtualBox.
MSG
