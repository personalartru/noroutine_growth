# No ! Routine — бот лид-магнита и growth-механики

Репозиторий закрывает две механики роста Telegram-канала `@noroutine2026`:

1. **Лид-магнит + бот.** Человек переходит по ссылке-диплинку, подписывается на
   канал, получает ZIP с 5 готовыми n8n-воркфлоу. Источник перехода
   фиксируется (`?start=site`, `?start=rutube`, `?start=youtube`…), так что видно,
   какой канал приводит подписчиков.
2. **Growth-материалы.** Текст закреплённого поста, список чатов и партнёрских
   каналов, готовые экспертные ответы для комментинга.

## Структура

```
bot.py                 бот выдачи лид-магнита (long polling, только requests)
build_materials.py     генератор 5 основных + 5 бонусных n8n-воркфлоу + сборка ZIP
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
python bot.py --check  # диагностика: бот, материал, доступ к каналу
python bot.py           # запуск (long polling, держите окно открытым)
```

`--check` отвечает на главный вопрос «почему бот молчит»: показывает, запущен
ли бот, лежит ли архив и видит ли бот участников канала. Если последняя
проверка не проходит — бот не администратор канала, и он не сможет проверить
подписку.

### Что нужно от Telegram

1. Создать бота: [@BotFather](https://t.me/BotFather) → `/newbot` → скопировать токен.
2. Добавить бота в канал `@noroutine2026` и назначить администратором
   (канал → Подписчики → Добавить подписчиков → выбрать бота). Права:
   «Публикация сообщений» + «Закрепление сообщений» + чтение участников.
   Бот должен быть администратором канала, иначе `getChatMember` не отдаст
   статус подписки.
3. Узнать `ADMIN_CHAT_ID` — написать боту любой текст и взять из лога
   (`events.jsonl`) значение `chat_id`.

### Как узнать ADMIN_CHAT_ID

Это числовой ID вашего чата с ботом (у личного аккаунта Telegram он
совпадает с ID пользователя). Три способа:

1. **Через @userinfobot** или **@getmyid_bot** — напишите любому из них,
   в ответе будет ваш ID (например `123456789`).
2. **Из лога бота**: после первого сообщения боту в `events.jsonl` появится
   строка вида `{"event": "start", "chat_id": 123456789, ...}` — возьмите
   значение `chat_id`.
3. **Через @RawDataBot** — он вернёт JSON с вашим `id`.

В `.env` пишите просто число, без плюса и кавычек:

```
ADMIN_CHAT_ID=123456789
```

### Переменные окружения

| Переменная | Назначение |
|---|---|
| `TELEGRAM_BOT_TOKEN` | токен бота от BotFather |
| `CHANNEL_USERNAME` | канал, подписка на который проверяется (по умолчанию `@noroutine2026`) |
| `CHANNEL_ID` | числовой ID канала — надёжнее ника, если проверка по юзернейму не сработает |
| `ADMIN_CHAT_ID` | **необязательно.** ID вашего чата, куда приходят уведомления «лид-магнит забрали». Без него бот работает, просто не присылает уведомления |
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
sudo mkdir -p /opt/noroutine-growth
sudo chown -R $USER /opt/noroutine-growth
git clone https://github.com/personalartru/noroutine_growth.git /opt/noroutine-growth
cd /opt/noroutine-growth
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
cp .env.example .env && nano .env        # токен BotFather, канал, ADMIN_CHAT_ID
sudo cp deploy/noroutine-bot.service /etc/systemd/system/
sudo systemctl enable --now noroutine-bot
./.venv/bin/python bot.py --check
journalctl -u noroutine-bot -f
```

### Обновление бота

```bash
cd /opt/noroutine-growth && sudo bash deploy/deploy.sh
```

Скрипт делает `git pull`, обновляет зависимости, пересобирает лид-магнит,
перезапускает сервис и печатает результат `--check`. После этого новые
изменения в репозитории попадают в бота одной командой.

### Docker

```bash
docker build -t noroutine-bot .
docker run -d --name noroutine-bot --env-file .env -v "$PWD/materials:/app/materials" noroutine-bot
```

Для продакшена вместо long polling можно переключиться на webhook
(публичный HTTPS-домен), но long polling проще и для бота с десятками
пользователей в сутки более чем достаточно.

## Кто может обновлять бота

Любой, у кого есть права на репозиторий `noroutine_growth`: правит код →
пушит в `main` → на сервере выполняется `sudo bash deploy/deploy.sh` (или
`systemctl restart noroutine-bot`, если лид-магнит не менялся).

Если сервер доступен по SSH — деплой и перезапуск можно отдать ассистенту:
достаточно добавить доступ (ключ) и указать путь `/opt/noroutine-growth`.
CI в репозитории дополнительно проверяет, что архив лид-магнита совпадает
с результатом `build_materials.py` (workflow `Check materials`).

## Вариант без сервера: бот в GitHub Actions

Если VPS пока нет — бот может работать прямо в GitHub Actions:

| Workflow | Что делает |
|---|---|
| `Check lead bot` | диагностика + сквозная проверка: выдаёт архив в личку админа |
| `Run lead bot (GitHub Actions)` | крутит polling бота ~8 минут, каждые 11 минут (schedule) |

Секреты, которые нужны обоим workflow (в репозитории `noroutine_growth`):

| Секрет | Значение |
|---|---|
| `LEAD_BOT_TOKEN` | токен бота @noroutine_ai_bot из BotFather |
| `LEAD_CHANNEL_USERNAME` | `@noroutine2026` |
| `LEAD_ADMIN_CHAT_ID` | `270479866` |
| `MAX_BOT_TOKEN` | токен MAX-бота (того же, что админ канала) — нужен для выдачи лид-магнита в MAX |
| `MAX_CHANNEL_ID` | chat_id канала в MAX, **с минусом**: `-71062363105923` |
| `MAX_ADMIN_CHAT_ID` | **ваш** user_id в MAX (куда приходят заявки) — `60669315`. Не путать с id самого бота (`527604700`) и с chat_id диалога |

**Чтобы бот работал непрерывно**, добавьте четвёртый секрет — classic PAT с
галочками `repo` и `workflow` (github.com/settings/tokens). Workflow тогда
ставит следующий цикл в очередь сам, и планировщик GitHub не нужен:

| Секрет | Значение |
|---|---|
| `DISPATCH_TOKEN` | classic PAT: scope `repo` + `workflow` |

Плюсы: ноль инфраструктуры, токен бота никогда не попадает в код. Минусы:
ответ бота может задержаться до ~11 минут (окно опроса 8 минут + запуск),
GitHub отключает scheduled-workflows при простое репозитория больше 60 дней.

Для мгновенных ответов — systemd на VPS или `deploy/k8s/lead-bot.yaml`
(манифесты под ваш кластер: Deployment + PVC под offset, `kubectl apply -f`).

## Постоянный деплой в Kubernetes (продакшн)

Манифесты в `deploy/k8s/` — по вашим конвенциям (namespace, PVC на состояние,
ConfigMap, Deployment с initContainer, который тянет код и ставит сертификаты
Минцифры). Один реплика: два поллера одного бота дают 409 Conflict.

**Раскатка вручную:**

```bash
# 1. секреты: заполнить .env.k8s в корне репозитория
#    TELEGRAM_BOT_TOKEN=... LEAD_CHANNEL_USERNAME=@noroutine2026
#    LEAD_ADMIN_CHAT_ID=270479866 MAX_BOT_TOKEN=...
#    MAX_ADMIN_CHAT_ID=60669315 MAX_PING_CHAT_ID=485434975
bash deploy/k8s/sync-secrets.sh
bash deploy/k8s/deploy.sh
```

**Раскатка из CI:** добавьте в репозиторий секрет `KUBECONFIG` — тогда workflow
`Deploy lead bot` сам применит манифесты и перезапустит под.

KUBECONFIG в публичном репозитории — это доступ к кластеру, поэтому не кладите
туда админский kubeconfig. Соберите ограниченный: сервис-аккаунт с правами
только в namespace `lead-bot`:

```bash
bash deploy/k8s/make-sa-kubeconfig.sh
```

Скрипт создаст сервис-аккаунт, настроит Role/RoleBinding в одном namespace,
выпустит токен на год и напечатает готовую base64-строку для секрета
`KUBECONFIG` (файл `deploy/k8s/sa-kubeconfig.yaml` в `.gitignore`). Любой коммит в `main`, затронувший код бота или манифесты,
автоматически уезжает в кластер.

**Важно:** после того как бот заработал в кластере, CI-цикл опроса
(`Run lead bot (GitHub Actions)`) надо отключить — иначе два поллера будут
мешать друг другу. Workflow `Deploy lead bot` отключает его сам после
успешного деплоя; включить обратно:

```bash
gh workflow enable "Run lead bot (GitHub Actions)"
```

## Деплой по кнопке (GitHub Actions)

Workflow `Deploy bot` сам подключается к серверу по SSH и выполняет
`deploy/deploy.sh`. Нужны секреты в репозитории:

| Секрет | Значение |
|---|---|
| `DEPLOY_HOST` | адрес сервера (например `123.45.67.89`) |
| `DEPLOY_USER` | пользователь с правом `sudo systemctl restart noroutine-bot` |
| `DEPLOY_SSH_KEY` | приватный SSH-ключ (для деплоя) |

Дальше: любой push в `main` или ручной запуск workflow обновляет бота.
Для этого у пользователя в `sudoers` должно быть:

```
$USER ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart noroutine-bot
```

## Лид-магнит и заявки в MAX

MAX-бот (`noroutine_bot`, администратор канала `max.ru/channel_noroutine`)
работает по сценарию 1:1 с Telegram-ботом:

- **«/start»** → если подписан на канал: «Готово, спасибо за подписку!» +
  архив с 5 воркфлоу и кнопкой «Хочу такую же под свой процесс»;
  если нет — приветствие с кнопками «Подписаться на канал» и «Я подписался»;
- **«Я подписался»** → бот перепроверяет подписку и выдаёт архив;
- **«Хочу такую же под свой процесс»** → «Опишите задачу одним сообщением…»;
- **любой другой текст** → заявка: вам в личный чат MAX уходит уведомление
  (имя, @username, user_id, ссылка на профиль, текст запроса), а пользователю
  в личку — «Принял запрос — изучаю и скоро свяжусь с вами.» с архивом.

Тексты в MAX и Telegram совпадают дословно (`TEXT_HELLO`, `TEXT_AFTER_SUB`,
`TEXT_REQUEST_SENT`, `TEXT_TASK_PROMPT`).

**Особенность MAX:** бот может писать только тем, кто его запустил. Поэтому
если человек комментирует в канале, но бота не открывал, личка недоступна —
тогда в чат обсуждения уходит кнопка-диплинк «Открыть бота и забрать архив»
(`https://max.ru/<bot>?start=lead`), и по нажатию бот выдаёт архив уже в личку.
Текст запроса при этом сохраняется между циклами в `.max_pending.json`
(в кеше Actions).

## Как приходят заявки

Любое сообщение от пользователя, кроме команд, считается заявкой:
бот пересылает его в чат `ADMIN_CHAT_ID` (ваш личный чат) с именем,
`user_id`, источником перехода и прямой ссылкой на профиль — можно ответить
в один клик. Пользователю уходит подтверждение, что запрос принят.

В архиве сообщения:
```
{"event": "request", "user_id": 777, "username": "ivan", "source": "bot",
 "text": "Нужна автоматизация отчётов по продажам", "ts": "..."}
```

Кнопка «Хочу такую же под свой процесс» под архивом запускает этот же сценарий.

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
| Закреплённый пост, автопостинг в MAX, футер с лид-магнитом и 6 переписанных постов | `personalartru/noroutine_posting`, ветка `feat/growth-fixes` (всё в одной ветке) |
| CTA-блоки, QR и блок лид-магнита на сайте | `personalartru/noroutine`, ветка `feat/channels-cta` |
| Тексты взаимопиара в MAX и кросс-ссылки Telegram ↔ MAX | `growth/max_mutual_promo.md` |

## Интеграция с сайтом

1. Создайте бота и получите юзернейм.
2. Сгенерируйте QR для диплинка:

   ```bash
   python scripts/make_qr.py "https://t.me/noroutine_ai_bot?start=site" ../noroutine/lead-qr.png
   ```

3. В `personalartru/noroutine` (ветка `feat/channels-cta`) замените `href`
   в блоке «// Лид-магнит» на `https://t.me/noroutine_ai_bot?start=site` и
   положите рядом `lead-qr.png`.
4. В описаниях видео на YouTube и Rutube — та же диплинка с меткой источника
   (`?start=youtube`, `?start=rutube`), чтобы видеть, какой площадка работает.

## Порядок запуска

1. Создать бота, добавить его администратором канала `@noroutine2026`.
2. `python build_materials.py` — собрать ZIP.
3. Задеплоить бота (systemd или Docker), заполнить `.env`, проверить `python bot.py --check`.
4. Проверить: `https://t.me/noroutine_ai_bot?start=test` → бот должен спросить
   подписку и выдать архив после подписки на канал.
5. Опубликовать и закрепить пост-визитку (workflow `Publish pinned post`
   в `noroutine_posting`, вручную).
6. Поставить ссылки на бота на сайт, в описания видео, в посты.
7. Комментинг — по шаблонам из `growth/commenting_templates.md`.

