# Процесс разработки и деплоя

## Сервера

| Роль | Адрес |
|------|-------|
| Разработка | текущий сервер, `/opt/bots/captcha_bot_repo/` |
| Продакшн | `194.87.133.24`, `/opt/bots/captcha_bot_repo/` |

## Разработка → GitHub

```bash
cd /opt/bots/captcha_bot_repo
git add -A
git commit -m "описание изменений"
git push origin main
```

## Деплой на продакшн

Зайти на прод:
```bash
ssh root@194.87.133.24
```

Задеплоить:
```bash
/opt/bots/deploy.sh
```

Или вручную:
```bash
cd /opt/bots/captcha_bot_repo
git pull origin main
docker compose up -d --build
```

## Что НЕ хранится в git (хранится только на серверах)

- `captcha_bot/.env` — токен бота и секреты
- `nginx/ssl/` — SSL-сертификаты
- `redis/data/` — данные Redis

## Репозиторий

https://github.com/pavelgla/capcha_bot
