# Captcha Bot — контекст проекта

Telegram-бот верификации новых участников чата через капчу.

## Стек

- Python + aiogram
- Redis (хранение состояния капчи)
- FastAPI/uvicorn (веб-панель администратора)
- Nginx (реверс-прокси, SSL)
- Docker Compose (4 сервиса: redis, captcha_bot, captcha_web, nginx)

## Сервер

| Роль | Адрес | Путь |
|------|-------|------|
| Prod/Dev | 72.56.112.182 | `/opt/bots/captcha_bot_repo/` |

## Деплой

```bash
cd /opt/bots/captcha_bot_repo
git add -A && git commit -m "..." && git push origin main
docker compose up -d
```

## Что НЕ хранится в git

- `captcha_bot/.env` — токен бота и прочие секреты
- `nginx/ssl/` — SSL-сертификаты
- `redis/data/` — данные Redis

## Структура кода

```
captcha_bot/
  bot.py              # точка входа
  config.py
  handlers/
    new_member.py     # вход/выход пользователей, таймаут капчи
    captcha_callback.py
    admin_commands.py
  middlewares/
  services/
  web/                # FastAPI веб-панель
```

## Важно

- Бот должен работать только на одном сервере — конфликт getUpdates
- При переключении: сначала `docker compose down` на старом сервере
- Nginx здесь же проксирует estelad (`estelad.console10.ru` → `midgard-game:80`)
- GitHub: https://github.com/pavelgla/capcha_bot
