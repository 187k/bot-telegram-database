# Деплой на сервер

Ниже два способа: через systemd (рекомендуется, без Docker) и через Docker Compose.
Примеры для Ubuntu/Debian.

## Что понадобится

- Сервер с Ubuntu 22.04+ и доступом по SSH.
- Токен бота от [@BotFather](https://t.me/BotFather).
- Telegram ID всех сотрудников (узнать можно у [@userinfobot](https://t.me/userinfobot)).

Исходящий интернет нужен, открытых портов — нет: бот работает на long polling,
входящие соединения ему не требуются.

---

## Способ 1: systemd + venv

### 1. Подготовка сервера

```bash
sudo apt update && sudo apt install -y python3 python3-venv python3-pip
```

Отдельный пользователь без прав root:

```bash
sudo useradd --system --create-home --shell /usr/sbin/nologin botuser
sudo mkdir -p /opt/client-bot && sudo chown botuser:botuser /opt/client-bot
```

### 2. Загрузка кода

С локальной машины:

```bash
scp bot.py db.py requirements.txt bot.service .env.example user@SERVER:/tmp/
```

На сервере:

```bash
sudo mv /tmp/{bot.py,db.py,requirements.txt,.env.example} /opt/client-bot/
sudo chown -R botuser:botuser /opt/client-bot
```

### 3. Виртуальное окружение и зависимости

```bash
sudo -u botuser python3 -m venv /opt/client-bot/venv
sudo -u botuser /opt/client-bot/venv/bin/pip install -r /opt/client-bot/requirements.txt
```

### 4. Настройки

```bash
sudo -u botuser cp /opt/client-bot/.env.example /opt/client-bot/.env
sudo -u botuser nano /opt/client-bot/.env
```

Заполните:

```
BOT_TOKEN=123456:реальный_токен
EMPLOYEE_IDS=111111111,222222222,333333333
```

Токен не должен быть доступен другим пользователям системы:

```bash
sudo chmod 600 /opt/client-bot/.env
```

### 5. Служба systemd

```bash
sudo cp /tmp/bot.service /etc/systemd/system/client-bot.service
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now client-bot
```

Проверка:

```bash
systemctl status client-bot
```

В логах при старте должна быть строка `Доступ разрешён сотрудникам: [...]`.

### 6. Логи и управление

```bash
sudo journalctl -u client-bot -f
```

```bash
sudo systemctl restart client-bot
```

### 7. Обновление кода

```bash
sudo -u botuser cp /tmp/bot.py /tmp/db.py /opt/client-bot/ && sudo systemctl restart client-bot
```

---

## Способ 2: Docker Compose

```bash
sudo apt update && sudo apt install -y docker.io docker-compose-v2
```

Скопируйте на сервер `bot.py`, `db.py`, `requirements.txt`, `Dockerfile`,
`docker-compose.yml`, `.env.example`, затем:

```bash
cp .env.example .env && nano .env
```

```bash
sudo docker compose up -d --build
```

Логи и перезапуск:

```bash
sudo docker compose logs -f
```

```bash
sudo docker compose restart
```

База лежит в папке `./data/clients.db` на хосте (volume), контейнер можно
пересоздавать без потери данных.

---

## Добавление нового сотрудника

1. Сотрудник пишет боту — бот ответит отказом и покажет его Telegram ID.
2. Добавьте этот ID в `EMPLOYEE_IDS` в `.env`.
3. Перезапустите бота: `sudo systemctl restart client-bot`
   (или `sudo docker compose restart`).

Список сотрудников читается при запуске, поэтому перезапуск обязателен.

## Переход со старой версии (числовые ID клиентов)

Если на сервере уже лежит база прежней версии, где клиенты хранились числовыми
Telegram ID, при первом запуске бот сам создаст новую таблицу `clients`
с `@username`:

- если старая таблица была пустой — она просто удаляется;
- если в ней были записи — она сохраняется под именем `clients_old_ids`,
  данные остаются в базе, их можно посмотреть через `sqlite3`.

Отдельных действий не требуется, но перед обновлением сделайте бэкап (ниже).

## Резервная копия базы

Одной командой, безопасно для работающего бота:

```bash
sudo -u botuser sqlite3 /opt/client-bot/clients.db ".backup '/opt/client-bot/backup-$(date +%F).db'"
```

Для Docker путь к базе — `./data/clients.db`.

Автоматический бэкап каждую ночь (crontab root):

```bash
0 3 * * * sqlite3 /opt/client-bot/clients.db ".backup '/var/backups/client-bot-$(date +\%F).db'"
```

## Если бот не отвечает

| Симптом в логах | Причина |
|---|---|
| `Не задан BOT_TOKEN` | пустой или отсутствует `.env` / `EnvironmentFile` |
| `Не задан EMPLOYEE_IDS` | не указан список сотрудников |
| `Unauthorized` | неверный токен |
| `Отказано в доступе: id=...` | этого ID нет в `EMPLOYEE_IDS` |
| `TelegramConflictError` | бот уже запущен где-то ещё (два экземпляра) |
