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

Скрипт сам определяет нужна ли пересборка образов:
- если изменился `Dockerfile` или `requirements.txt` — выполняет `docker compose up -d --build`
- иначе — просто `docker compose up -d` (быстрее, без обращения к Docker Hub)

## Что НЕ хранится в git (хранится только на серверах)

- `captcha_bot/.env` — токен бота и секреты
- `nginx/ssl/` — SSL-сертификаты
- `redis/data/` — данные Redis

## Полезные команды на проде

```bash
# Посмотреть статус контейнеров
docker compose -f /opt/bots/captcha_bot_repo/docker-compose.yml ps

# Логи бота
docker compose -f /opt/bots/captcha_bot_repo/docker-compose.yml logs -f captcha_bot

# Перезапустить всё
docker compose -f /opt/bots/captcha_bot_repo/docker-compose.yml restart
```

## Репозиторий

https://github.com/pavelgla/capcha_bot
