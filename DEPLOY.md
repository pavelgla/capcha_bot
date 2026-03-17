# Процесс разработки и деплоя

## Сервер

Бот работает на единственном сервере: `72.56.112.182`, путь `/opt/bots/captcha_bot_repo/`.

## Workflow

```bash
cd /opt/bots/captcha_bot_repo

# 1. Закоммитить и запушить
git add -A
git commit -m "описание изменений"
git push origin main

# 2. Применить изменения
docker compose up -d --build   # если менялся Dockerfile или requirements.txt
docker compose up -d           # иначе (быстрее)
```

## Что НЕ хранится в git (хранится только на сервере)

- `captcha_bot/.env` — токен бота и секреты
- `nginx/ssl/` — SSL-сертификаты
- `redis/data/` — данные Redis

## Полезные команды

```bash
# Статус контейнеров
docker compose ps

# Логи бота
docker compose logs -f captcha_bot

# Перезапустить всё
docker compose restart
```

## Репозиторий

https://github.com/pavelgla/capcha_bot
