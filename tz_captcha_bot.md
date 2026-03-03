# Техническое задание: Telegram-бот2 верификации новых участников чата

## 1. Цель

Создать Telegram-бота, который автоматически проверяет каждого нового участника чата с помощью математической загадки. До прохождения проверки пользователь замьючен. Если не прошёл — мьют навсегда.

---

## 2. Стек

| Что | Чем |
|---|---|
| Язык | Python 3.11+ |
| Фреймворк | aiogram 3.x |
| Хранилище | Redis (один экземпляр на все боты) |
| Контейнеры | Docker + Docker Compose |
| CI/CD | GitHub Actions |
| Сервер | VPS Ubuntu 22.04 (Timeweb Cloud, тариф «Начальный») |

---

## 3. Сценарий работы

```
Новый пользователь вступает в чат
        ↓
Бот мьютит пользователя (restrict_chat_member)
        ↓
Проверить muted_forever:<user_id> в Redis
   Есть запись → мьютить сразу, капчу не показывать
   Нет записи  → сгенерировать задачку, отправить капчу
        ↓
[Пользователь нажимает кнопку]
   ✅ Верно               → снять мьют, удалить сообщение
   ❌ Попытки исчерпаны   → мьют навсегда, удалить сообщение
   ⏱ Таймаут             → мьют навсегда, удалить сообщение
```

---

## 4. Капча: математическая загадка

### Формат A — арифметика
- «Сколько будет 8 × 7?»
- «Сколько будет 144 ÷ 12?»
- «Сколько будет 25 + 37?»

### Формат B — словесная задача
- «У меня 3 яблока, я съел 1, потом нашёл ещё 2. Сколько у меня яблок?»
- «Ряд чисел: 2, 4, 8, 16, ___. Какое следующее?»

### Отображение
- 4 инлайн-кнопки: один верный ответ, три правдоподобных неверных (близкие числа)
- Кнопки перемешиваются случайно при каждой генерации
- Формат сообщения:

```
👋 @username, добро пожаловать!

Для доступа к чату решите задачку:

Сколько будет 6 × 9?

  [42]   [54]   [63]   [48]

У вас 2 попытки. Осталось: 5:00
```

---

## 5. Функциональные требования

### 5.1 Вступление нового пользователя

- Подписаться на `ChatMemberUpdated`
- При вступлении:
  1. `restrict_chat_member` — запретить `can_send_messages`, `can_send_media_messages`, `can_send_other_messages`
  2. Проверить `muted_forever:<user_id>` — если есть, мьютить и выйти
  3. Сгенерировать задачку, сохранить в Redis с TTL
  4. Отправить сообщение с капчей в чат с @упоминанием
  5. Запустить asyncio таймер

### 5.2 Обработка ответа

Обрабатывать `CallbackQuery` только от пользователя, которому адресована капча.
Чужое нажатие → эфемерный ответ «Эта проверка не для вас».

**Верный ответ:**
1. Снять ограничения (`restrict_chat_member` с правами по умолчанию)
2. Удалить сообщение с капчей
3. Отправить «✅ @username прошёл(а) проверку!» → автоудалить через 10 сек
4. Удалить запись из Redis

**Неверный ответ:**
1. Уменьшить счётчик попыток
2. Если попыток > 0 → обновить сообщение «❌ Неверно. Осталось попыток: N»
3. Если попыток = 0:
   - Удалить сообщение с капчей
   - Записать `muted_forever:<user_id>` без TTL
   - Отправить «🚫 @username не прошёл(а) проверку.» → автоудалить через 15 сек

### 5.3 Таймаут

1. Удалить сообщение с капчей
2. Записать `muted_forever:<user_id>` без TTL
3. Мьют уже действует — ничего дополнительного

### 5.4 Команды администратора

Доступны только администраторам чата (проверять через `get_chat_member`).

| Команда | Действие |
|---|---|
| `/unmute <user_id>` | Снять мьют, удалить из `muted_forever` |
| `/mutestat` | Количество замьюченных навсегда |
| `/banned` | Список user_id из `muted_forever` |

---

## 6. Конфигурация (`.env`)

```env
BOT_TOKEN=               # Токен от @BotFather
CHAT_ID=                 # ID чата, например -1001234567890
ADMIN_IDS=123456,789012  # User ID администраторов через запятую
CAPTCHA_TIMEOUT=300      # Таймаут в секундах (по умолчанию 300)
CAPTCHA_ATTEMPTS=2       # Количество попыток
REDIS_URL=redis://redis:6379  # Имя сервиса из docker-compose
```

---

## 7. Модель данных в Redis

```
# Активная капча (TTL = CAPTCHA_TIMEOUT)
captcha:<user_id>  →  JSON {
    "correct_answer": 54,
    "attempts_left": 2,
    "message_id": 12345,
    "task_text": "Сколько будет 6 × 9?"
}

# Постоянный мьют (без TTL)
muted_forever:<user_id>  →  "1"
```

---

## 8. Структура проекта

```
captcha_bot/
├── bot.py
├── config.py
├── handlers/
│   ├── new_member.py
│   ├── captcha_callback.py
│   └── admin_commands.py
├── services/
│   ├── captcha_generator.py
│   ├── mute_manager.py
│   └── storage.py
├── middlewares/
│   └── chat_filter.py
├── Dockerfile
├── .env.example
├── requirements.txt
└── README.md
```

---

## 9. Права бота в чате

Бот должен быть **администратором** с правами:
- ✅ `can_restrict_members`
- ✅ `can_delete_messages`

---

## 10. Обработка ошибок

- `TelegramForbiddenError` — логировать, не падать
- Пользователь покинул чат до таймаута — отменить asyncio task, удалить запись
- Redis недоступен — fallback на in-memory dict с предупреждением в логах

---

## 11. Требования к коду

- Типизация (`typing`, `dataclasses` или `pydantic`)
- Логирование через `logging` (уровень `INFO`, формат с timestamp)
- Юнит-тесты: `captcha_generator.py`, `storage.py`

---

## 12. Инфраструктура и деплой

### 12.1 Dockerfile (captcha_bot/Dockerfile)

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "bot.py"]
```

### 12.2 docker-compose.yml

Файл лежит в `/opt/bots/` на сервере и управляет всеми ботами сразу.
Каждый новый бот добавляется как отдельный сервис.

```yaml
services:

  redis:
    image: redis:7-alpine
    restart: always
    volumes:
      - ./redis/data:/data

  captcha_bot:
    build: ./captcha_bot
    restart: always
    env_file: ./captcha_bot/.env
    depends_on:
      - redis

  # Будущий бот — добавить аналогично:
  # another_bot:
  #   build: ./another_bot
  #   restart: always
  #   env_file: ./another_bot/.env
  #   depends_on:
  #     - redis
```

### 12.3 CI/CD через GitHub Actions

Файл `.github/workflows/deploy.yml` в репозитории бота.

**Принцип работы:**
- Триггер: `push` в ветку `main`
- GitHub Actions подключается к серверу по SSH
- Выполняет `git pull` и перезапускает только контейнер этого бота
- Остальные боты не затрагиваются

```yaml
name: Deploy captcha_bot

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to VPS
        uses: appleboy/ssh-action@v1.0.3
        with:
          host: ${{ secrets.SERVER_HOST }}
          username: ${{ secrets.SERVER_USER }}
          key: ${{ secrets.SERVER_SSH_KEY }}
          script: |
            cd /opt/bots/captcha_bot
            git pull origin main
            cd /opt/bots
            docker-compose build captcha_bot
            docker-compose restart captcha_bot
```

**GitHub Secrets** (Settings → Secrets → Actions):

| Secret | Значение |
|---|---|
| `SERVER_HOST` | IP-адрес сервера |
| `SERVER_USER` | `root` или имя пользователя |
| `SERVER_SSH_KEY` | Приватный SSH-ключ (содержимое `~/.ssh/id_rsa`) |

### 12.4 Скрипт первоначальной настройки сервера (setup.sh)

Запускается **один раз** после покупки VPS. Создать файл `setup.sh` со следующими шагами:

1. Обновить пакеты (`apt update && apt upgrade`)
2. Установить Docker (официальный скрипт `get.docker.com`)
3. Установить Docker Compose plugin
4. Установить git
5. Создать структуру папок:
   ```
   /opt/bots/
   /opt/bots/redis/data/
   /opt/bots/captcha_bot/
   ```
6. Настроить Docker на автозапуск (`systemctl enable docker`)
7. Вывести инструкцию: что делать дальше

### 12.5 Структура на сервере

```
/opt/bots/
├── docker-compose.yml        # управление всеми ботами
├── redis/
│   └── data/                 # данные Redis (persist)
├── captcha_bot/              # код бота (git clone сюда)
│   ├── .env                  # ← только на сервере, НЕ в git
│   └── (остальные файлы из репо)
├── bot_2/                    # будущий бот
│   └── .env
└── bot_3/
    └── .env
```

**Важно:** `.env` файлы с токенами хранятся только на сервере, в `.gitignore`.

---

## 13. Полезные команды на сервере

```bash
# Первый запуск всего
cd /opt/bots && docker-compose up -d

# Посмотреть статус всех ботов
docker-compose ps

# Логи конкретного бота в реальном времени
docker-compose logs -f captcha_bot

# Перезапустить одного бота вручную
docker-compose restart captcha_bot

# Обновить и перезапустить вручную (без CI/CD)
cd /opt/bots/captcha_bot && git pull
cd /opt/bots && docker-compose build captcha_bot && docker-compose restart captcha_bot

# Остановить всё
docker-compose down
```

---

## 14. Порядок запуска с нуля

1. Купить VPS на Timeweb (Ubuntu 22.04, тариф «Начальный»)
2. Подключиться по SSH, запустить `setup.sh`
3. Создать бота через @BotFather, получить токен
4. Сделать бота администратором чата
5. `git clone <репо>` в `/opt/bots/captcha_bot/`
6. Создать `/opt/bots/captcha_bot/.env` с токеном и CHAT_ID
7. `cd /opt/bots && docker-compose up -d`
8. Добавить GitHub Secrets (`SERVER_HOST`, `SERVER_USER`, `SERVER_SSH_KEY`)
9. Следующие обновления: `git push` → деплой автоматически

---

## 15. Критерии готовности

- [ ] Новый участник мьютится немедленно при вступлении
- [ ] Капча — 4 инлайн-кнопки с вариантами ответа
- [ ] Верный ответ → мьют снят, сообщение удалено
- [ ] Исчерпаны попытки → мьют навсегда, сообщение удалено
- [ ] Таймаут → мьют навсегда, сообщение удалено
- [ ] Повторный вход замьюченного → мьют сразу, без капчи
- [ ] Чужое нажатие на кнопку → эфемерный ответ
- [ ] Команды `/unmute`, `/mutestat`, `/banned` работают только для администраторов
- [ ] Конфигурация через `.env`
- [ ] `Dockerfile` собирается без ошибок
- [ ] `docker-compose.yml` поднимает бота + Redis одной командой
- [ ] `.github/workflows/deploy.yml` деплоит при push в main
- [ ] `setup.sh` настраивает чистый Ubuntu-сервер
- [ ] `.env` в `.gitignore`
- [ ] `README.md` с полной инструкцией по запуску
