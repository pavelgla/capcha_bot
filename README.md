# Captcha Bot

Telegram-бот для верификации новых участников чата с помощью математических загадок.

## Сценарий

```
Новый участник вступает в чат
        ↓
Бот мьютит пользователя
        ↓
Проверяем: он был замьючен навсегда раньше?
   Да → мьют сразу, без капчи
   Нет → отправить задачку (4 кнопки с вариантами)
        ↓
[Пользователь нажимает кнопку]
   ✅ Верно           → снять мьют, удалить сообщение
   ❌ Попытки кончились → мьют навсегда
   ⏱ Таймаут         → мьют навсегда
```

---

## Быстрый старт (первый раз)

### 1. Подготовить сервер

```bash
# Подключиться к VPS по SSH, затем:
curl -fsSL https://raw.githubusercontent.com/<your-repo>/main/setup.sh | sudo bash
```

Или скопировать `setup.sh` на сервер и запустить:

```bash
chmod +x setup.sh && sudo ./setup.sh
```

### 2. Создать бота и получить токен

1. Написать [@BotFather](https://t.me/BotFather)
2. `/newbot` → указать имя и username
3. Скопировать токен `123456789:AAF...`
4. Добавить бота в свой чат как **администратора** с правами:
   - ✅ Ограничивать участников
   - ✅ Удалять сообщения

### 3. Узнать CHAT_ID

Добавьте [@userinfobot](https://t.me/userinfobot) в чат или перешлите ему сообщение из чата.

### 4. Клонировать репозиторий на сервер

```bash
git clone https://github.com/<your-username>/<repo>.git /opt/bots/captcha_bot_repo
```

### 5. Создать .env

```bash
cp /opt/bots/captcha_bot_repo/captcha_bot/.env.example /opt/bots/captcha_bot_repo/captcha_bot/.env
nano /opt/bots/captcha_bot_repo/captcha_bot/.env
```

Заполнить все переменные (см. [.env.example](captcha_bot/.env.example)).

### 6. Запустить

```bash
cd /opt/bots/captcha_bot_repo
docker compose up -d
```

Проверить статус:

```bash
docker compose ps
docker compose logs -f captcha_bot
```

---

## Настройка CI/CD (GitHub Actions)

### Шаг 1: Создать SSH-ключ для GitHub Actions

Выполнить **на сервере**:

```bash
ssh-keygen -t ed25519 -C "github-actions" -f ~/.ssh/github_actions -N ""
cat ~/.ssh/github_actions.pub >> ~/.ssh/authorized_keys
```

### Шаг 2: Добавить GitHub Secrets

В репозитории: **Settings → Secrets and variables → Actions → New repository secret**

| Secret | Значение |
|--------|----------|
| `SERVER_HOST` | IP-адрес сервера |
| `SERVER_USER` | `root` (или имя пользователя) |
| `SERVER_SSH_KEY` | Вывод команды: `cat ~/.ssh/github_actions` |

### Шаг 3: Готово

Теперь каждый `git push` в ветку `main` автоматически:
1. Подключается к серверу по SSH
2. Делает `git pull` в `/opt/bots/captcha_bot_repo`
3. Пересобирает и перезапускает контейнер `captcha_bot`

---

## Как добавить второго бота

1. Создать папку `/opt/bots/captcha_bot_repo/another_bot/` и задеплоить туда код
2. Добавить секцию в `/opt/bots/captcha_bot_repo/docker-compose.yml`:

```yaml
  another_bot:
    build: ./another_bot
    restart: always
    env_file: ./another_bot/.env
    depends_on:
      redis:
        condition: service_healthy
```

3. Создать `/opt/bots/captcha_bot_repo/another_bot/.env` с токеном нового бота
4. Создать `.github/workflows/deploy.yml` в репозитории нового бота:

```yaml
name: Deploy another_bot

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
            cd /opt/bots/captcha_bot_repo/another_bot
            git pull origin main
            cd /opt/bots/captcha_bot_repo
            docker compose build another_bot
            docker compose restart another_bot
```

5. Добавить те же GitHub Secrets (`SERVER_HOST`, `SERVER_USER`, `SERVER_SSH_KEY`)

> Redis уже запущен — новый бот использует тот же экземпляр автоматически.

---

## Полезные команды на сервере

```bash
# Статус всех контейнеров
cd /opt/bots/captcha_bot_repo && docker compose ps

# Логи бота в реальном времени
docker compose logs -f captcha_bot

# Перезапустить бота вручную
docker compose restart captcha_bot

# Обновить вручную без CI/CD
cd /opt/bots/captcha_bot_repo && git pull
docker compose build captcha_bot && docker compose restart captcha_bot

# Остановить всё
docker compose down

# Остановить и удалить данные Redis (осторожно!)
docker compose down -v
```

## Команды администратора в чате

| Команда | Описание |
|---------|----------|
| `/unmute <user_id>` | Снять постоянный мьют с пользователя |
| `/mutestat` | Сколько пользователей замьючено навсегда |
| `/banned` | Список user_id замьюченных навсегда |

---

## Структура на сервере

```
/opt/bots/
└── captcha_bot_repo/            ← git clone сюда
    ├── docker-compose.yml       ← управление всеми ботами
    ├── captcha_bot/             ← код бота
    │   ├── .env                 ← ТОЛЬКО на сервере, не в git!
    │   └── ...
    ├── nginx/
    ├── redis/
    │   └── data/                ← данные Redis (persist)
    └── another_bot/             ← будущие боты
        └── .env
```
