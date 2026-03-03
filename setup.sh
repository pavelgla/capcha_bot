#!/bin/bash
set -e

# Colours
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}=== Настройка VPS для деплоя Telegram-ботов ===${NC}"
echo ""

if [[ $EUID -ne 0 ]]; then
    echo -e "${RED}Запустите скрипт от root: sudo ./setup.sh${NC}"
    exit 1
fi

# ── 1. Обновление пакетов ────────────────────────────────────────────────────
echo -e "${YELLOW}[1/6] Обновление пакетов...${NC}"
apt update -y
apt upgrade -y

# ── 2. Установка Docker ──────────────────────────────────────────────────────
echo -e "${YELLOW}[2/6] Установка Docker...${NC}"
if command -v docker &>/dev/null; then
    echo "Docker уже установлен: $(docker --version)"
else
    curl -fsSL https://get.docker.com | sh
    echo "Docker установлен: $(docker --version)"
fi

# ── 3. Установка Docker Compose ──────────────────────────────────────────────
echo -e "${YELLOW}[3/6] Установка Docker Compose...${NC}"
if command -v docker-compose &>/dev/null; then
    echo "Docker Compose уже установлен: $(docker-compose --version)"
else
    COMPOSE_VERSION=$(curl -fsSL https://api.github.com/repos/docker/compose/releases/latest \
        | grep '"tag_name":' | sed -E 's/.*"v([^"]+)".*/\1/')
    curl -fsSL \
        "https://github.com/docker/compose/releases/download/v${COMPOSE_VERSION}/docker-compose-$(uname -s)-$(uname -m)" \
        -o /usr/local/bin/docker-compose
    chmod +x /usr/local/bin/docker-compose
    echo "Docker Compose ${COMPOSE_VERSION} установлен"
fi

# ── 4. Установка git ─────────────────────────────────────────────────────────
echo -e "${YELLOW}[4/6] Установка git...${NC}"
apt install -y git
echo "git установлен: $(git --version)"

# ── 5. Создание структуры папок ──────────────────────────────────────────────
echo -e "${YELLOW}[5/6] Создание структуры /opt/bots/...${NC}"
mkdir -p /opt/bots/redis/data
mkdir -p /opt/bots/captcha_bot
chmod 755 /opt/bots
echo "Папки созданы:"
echo "  /opt/bots/"
echo "  /opt/bots/redis/data/"
echo "  /opt/bots/captcha_bot/"

# ── 6. Автозапуск Docker ─────────────────────────────────────────────────────
echo -e "${YELLOW}[6/6] Настройка автозапуска Docker...${NC}"
systemctl enable docker
systemctl start docker
echo "Docker включён в автозапуск"

# ── Итог ─────────────────────────────────────────────────────────────────────
SERVER_IP=$(curl -fsSL ifconfig.me 2>/dev/null || echo "YOUR_SERVER_IP")

echo ""
echo -e "${GREEN}=== Настройка завершена! ===${NC}"
echo ""
echo "Дальнейшие шаги:"
echo ""
echo "  1. Клонируйте репозиторий бота:"
echo "     git clone <URL_репозитория> /opt/bots/captcha_bot"
echo ""
echo "  2. Создайте .env с токеном:"
echo "     cp /opt/bots/captcha_bot/.env.example /opt/bots/captcha_bot/.env"
echo "     nano /opt/bots/captcha_bot/.env"
echo ""
echo "  3. Скопируйте docker-compose.yml на уровень /opt/bots/:"
echo "     cp /opt/bots/captcha_bot/docker-compose.yml /opt/bots/"
echo ""
echo "  4. Запустите всё:"
echo "     cd /opt/bots && docker-compose up -d"
echo ""
echo "  5. Настройте GitHub Secrets (Settings → Secrets → Actions):"
echo "     SERVER_HOST    = ${SERVER_IP}"
echo "     SERVER_USER    = root"
echo "     SERVER_SSH_KEY = содержимое ~/.ssh/id_rsa"
echo ""
echo "  Генерация SSH-ключа (если нужен):"
echo "     ssh-keygen -t ed25519 -C 'github-actions'"
echo "     cat ~/.ssh/id_ed25519.pub >> ~/.ssh/authorized_keys"
echo "     cat ~/.ssh/id_ed25519   # скопируйте в SERVER_SSH_KEY"
