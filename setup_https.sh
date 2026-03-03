#!/usr/bin/env bash
# setup_https.sh — Настройка HTTPS (nginx + самоподписанный сертификат)
# для веб-панели captcha_bot на VPS без домена.
#
# Использование (запускать от root на VPS):
#   bash setup_https.sh
#
# После выполнения панель будет доступна по адресу:
#   https://194.87.133.24
# Браузер покажет предупреждение о самоподписанном сертификате —
# нажми «Дополнительно» → «Перейти на сайт» чтобы принять исключение.

set -e

SERVER_IP="194.87.133.24"
INTERNAL_PORT="8080"          # порт FastAPI внутри Docker
CERT_DIR="/etc/nginx/ssl/captcha_web"

# ── 1. Nginx ──────────────────────────────────────────────────────────────────

echo "==> [1/5] Устанавливаем nginx..."
apt-get update -q
apt-get install -y nginx openssl

# ── 2. Самоподписанный сертификат ─────────────────────────────────────────────

echo "==> [2/5] Создаём самоподписанный сертификат для IP $SERVER_IP (10 лет)..."
mkdir -p "$CERT_DIR"

openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
  -keyout "$CERT_DIR/privkey.pem" \
  -out   "$CERT_DIR/fullchain.pem" \
  -subj  "/CN=$SERVER_IP" \
  -addext "subjectAltName=IP:$SERVER_IP"

chmod 600 "$CERT_DIR/privkey.pem"
echo "    Сертификат: $CERT_DIR/fullchain.pem"

# ── 3. Конфиг nginx ───────────────────────────────────────────────────────────

echo "==> [3/5] Настраиваем nginx (reverse proxy)..."

cat > /etc/nginx/sites-available/captcha_web << EOF
# HTTP → HTTPS redirect
server {
    listen 80;
    server_name $SERVER_IP;
    return 301 https://\$host\$request_uri;
}

# HTTPS → FastAPI (localhost:$INTERNAL_PORT)
server {
    listen 443 ssl;
    server_name $SERVER_IP;

    ssl_certificate     $CERT_DIR/fullchain.pem;
    ssl_certificate_key $CERT_DIR/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;
    ssl_session_cache   shared:SSL:10m;

    # Обязательно для SSE (Server-Sent Events): отключаем буферизацию
    proxy_buffering     off;
    proxy_cache         off;

    location / {
        proxy_pass         http://127.0.0.1:$INTERNAL_PORT;
        proxy_http_version 1.1;
        proxy_set_header   Host              \$host;
        proxy_set_header   X-Real-IP         \$remote_addr;
        proxy_set_header   X-Forwarded-For   \$proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto \$scheme;
        proxy_set_header   Connection        "";

        # Длинный таймаут для SSE-соединений
        proxy_read_timeout  3600s;
        proxy_send_timeout  3600s;
    }
}
EOF

# Включаем сайт, убираем дефолтный
ln -sf /etc/nginx/sites-available/captcha_web \
       /etc/nginx/sites-enabled/captcha_web
rm -f /etc/nginx/sites-enabled/default

# Проверяем конфиг
nginx -t

# ── 4. UFW ────────────────────────────────────────────────────────────────────

echo "==> [4/5] Настраиваем UFW..."
ufw allow 80/tcp   comment "HTTP (redirect to HTTPS)"
ufw allow 443/tcp  comment "HTTPS captcha_web"
# Закрываем прямой доступ к порту 8080 снаружи
ufw deny  8080/tcp 2>/dev/null || true
echo "    Текущие правила:"
ufw status numbered | grep -E "8080|80|443" || true

# ── 5. Запускаем nginx ────────────────────────────────────────────────────────

echo "==> [5/5] Запускаем nginx..."
systemctl enable nginx
systemctl restart nginx

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  ✅ HTTPS настроен!                                         ║"
echo "║                                                              ║"
echo "║  Открой в браузере:  https://$SERVER_IP              ║"
echo "║                                                              ║"
echo "║  Первый раз браузер покажет предупреждение:                  ║"
echo "║  «Подключение не защищено» или «Ваше соединение не          ║"
echo "║   является приватным» — это нормально для самоподписанного  ║"
echo "║  сертификата.                                                ║"
echo "║  Нажми: Дополнительно → Перейти на сайт                     ║"
echo "╚══════════════════════════════════════════════════════════════╝"
