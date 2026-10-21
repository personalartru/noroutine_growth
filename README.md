# No ! Routine — бот лид-магнита и growth-механики

Репозиторий закрывает две механики роста Telegram-канала `@noroutine2026`:

1. **Лид-магнит + бот.** Человек переходит по ссылке-диплинку, подписывается на
   канал, получает ZIP с 10 готовыми n8n-свяблонами. Источник перехода
   фиксируется (`?start=site`, `?start=rutube`, `?start=youtube`…), так что видно,
   какой канал приводит подписчиков.
2. **Growth-материалы.** Текст закреплённого поста, список чатов и партнёрских
   каналов, готовые экспертные ответы для комментинга.

## Структура

```
bot.py                 бот выдачи лид-магнита (long polling, только requests)
build_materials.py     генератор 10 n8n-шаблонов + сборка ZIP
materials/             готовый лид-магнит (README + workflows/ + functions/)
growth/                pinned_post.md, chats_and_partners.md, commenting_templates.md
deploy/                systemd-юнит и Dockerfile
```

## Быстрый старт

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # вписать токен и admin chat id
python build_materials.py
python bot.py
```

### Что нужно от Telegram

1. Создать бота: [@BotFather](https://t.me/BotFather) → `/newbot` → скопировать токен.
2. Добавить бота в канал `@noroutine2026` и назначить администратором
   (канал → Подписчики → Добавить подписчиков → выбрать бота). Права:
   «Публикация сообщений» + «Закрепление сообщений» + чтение участников.
   Бот должен быть администратором канала, иначе `getChatMember` не отдаст
   статус подписки.
3. Узнать `ADMIN_CHAT_ID` — написать боту любой текст и взять из лога
   (`events.jsonl`) значение `chat_id`.

### Переменные окружения

| Переменная | Назначение |
|---|---|
| `TELEGRAM_BOT_TOKEN` | токен бота от BotFather |
| `CHANNEL_USERNAME` | канал, подписка на который проверяется (по умолчанию `@noroutine2026`) |
| `CHANNEL_ID` | числовой ID канала — надёжнее ника, если проверка по юзернейму не сработает |
| `ADMIN_CHAT_ID` | чат, куда приходят уведомления о заборе лид-магнита |
| `MATERIALS_PATH` | путь к ZIP (по умолчанию `materials/noroutine-n8n-pack.zip`) |
| `EVENTS_LOG` | файл лога событий (по умолчанию `events.jsonl`) |

### Диплинки

```
https://t.me/<bot_username>?start=site      — с сайта
https://t.me/<bot_username>?start=rutube     — из Rutube
https://t.me/<bot_username>?start=youtube    — из YouTube
https://t.me/<bot_username>?start=dzen       — из Дзена
https://t.me/<bot_username>?start=max        — из MAX
https://t.me/<bot_username>?start=vk         — из VK
```

Источник попадает в `events.jsonl` и в уведомление админу — видно, какой
канал приводит подписчиков, а какой даёт пустой клик.

## Деплой

### systemd

```bash
sudo cp deploy/noroutine-bot.service /etc/systemd/system/
sudo systemctl enable --now noroutine-bot
journalctl -u noroutine-bot -f
```

### Docker

```bash
docker build -t noroutine-bot .
docker run -d --name noroutine-bot --env-file .env -v "$PWD/materials:/app/materials" noroutine-bot
```

Для продакшена вместо long polling можно переключиться на webhook
(публичный HTTPS-домен), но long polling проще и для бота с десятками
пользователей в сутки более чем достаточно.

## Лог событий

`events.jsonl` — по строке на событие:

```json
{"event": "start", "chat_id": 123, "user_id": 456, "username": "ivan", "source": "site", "ts": "2026-10-21T09:00:00+00:00"}
{"event": "material_delivered", "chat_id": 123, "source": "site", "ts": "2026-10-21T09:00:03+00:00"}
```

Ключевое: `material_delivered` — это уже подписчик, пришедший за материалом.
Считайте конверсию как `material_delivered / start` по каждому источнику.

## Как обновлять лид-магнит

```bash
python build_materials.py   # пересоберёт materials/workflows/*.json и ZIP
systemctl restart noroutine-bot
```

Файл отдаётся заново при каждом `/material`, поэтому новые шаблоны можно
выкатывать без правок в боте.

## Связанные репозитории

| Что | Где |
|---|---|
| Закреплённый пост канала + скрипт `publish_pinned.py` | `personalartru/noroutine_posting`, ветка `feat/pinned-post` |
| Автопостинг в MAX | `personalartru/noroutine_posting`, ветка `feat/max-crossposting` |
| CTA-блоки и QR на сайте | `personalartru/noroutine`, ветка `feat/channels-cta` |

## Интеграция с сайтом

1. Создайте бота и получите юзернейм.
2. Сгенерируйте QR для диплинка:

   ```bash
   python scripts/make_qr.py "https://t.me/<BOT_USERNAME>?start=site" ../noroutine/lead-qr.png
   ```

3. В `personalartru/noroutine` (ветка `feat/channels-cta`) замените `href`
   в блоке «// Лид-магнит» на `https://t.me/<BOT_USERNAME>?start=site` и
   положите рядом `lead-qr.png`.
4. В описаниях видео на YouTube и Rutube — та же диплинка с меткой источника
   (`?start=youtube`, `?start=rutube`), чтобы видеть, какой площадка работает.

## Порядок запуска

1. Создать бота, добавить его администратором канала `@noroutine2026`.
2. `python build_materials.py` — собрать ZIP.
3. Задеплоить бота (systemd или Docker), заполнить `.env`.
4. Проверить: `https://t.me/<BOT_USERNAME>?start=test` → бот должен спросить
   подписку и выдать архив после подписки на канал.
5. Опубликовать и закрепить пост-визитку (workflow `Publish pinned post`
   в `noroutine_posting`, вручную).
6. Поставить ссылки на бота на сайт, в описания видео, в посты.
7. Комментинг — по шаблонам из `growth/commenting_templates.md`.

