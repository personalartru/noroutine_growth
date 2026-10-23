# Сбор статистики просмотров MAX-канала

## Что это

Автоматический сбор просмотров постов из MAX Bot API и отображение в админке автопостинга.

## Как работает

1. **Каждые 6 часов** GitHub Actions запускает `fetch_channel_stats.py`
2. Скрипт вызывает MAX Bot API: `GET /messages?chat_id={CHANNEL_ID}&count=100`
3. Из ответа извлекаются данные о последних 100 постах:
   - `url` — публичная ссылка на пост
   - `timestamp` — время публикации
   - `views` — количество просмотров
   - `text` — первые 150 символов текста
4. Данные сохраняются в `max_channel_stats.json` в репозитории `personalartru/noroutine_posting`
5. Админка автопостинга (https://personalartru.github.io/noroutine_posting/) загружает этот файл и отображает:
   - **Суммарно просмотров** — в виджете статистики
   - *(в будущем: графики, топ-посты, динамика)*

## Формат данных

```json
{
  "channel_id": "-71062363105923",
  "total_posts": 42,
  "total_views": 8534,
  "posts": [
    {
      "url": "https://max.ru/channel_noroutine/1234567890",
      "timestamp": 1729670400000,
      "datetime": "2024-10-23 12:00",
      "views": 245,
      "text": "5 готовых n8n-воркфлоу для рутины..."
    }
  ],
  "last_updated": "2024-10-23T12:34:56Z"
}
```

## Доступные метрики

✅ **Просмотры постов** (`stat.views`) — количество уникальных просмотров поста  
❌ **Лайки/реакции** — MAX Bot API не предоставляет эту информацию  
❌ **Подписчики/отписки** — нет endpoint для отслеживания динамики подписчиков  
❌ **Комментарии** — можно получить через `GET /messages/{post_id}/comments`, но не включено в текущую версию

## Локальный запуск

```bash
# Установить переменные
export MAX_BOT_TOKEN="ваш_токен"
export MAX_CHANNEL_ID="-71062363105923"

# Запустить сбор (последние 50 постов)
python3 fetch_channel_stats.py 50

# Вывод: JSON с данными
```

## GitHub Actions

### Workflow: `sync-channel-stats.yml`

**Триггеры:**
- Schedule: каждые 6 часов (`0 */6 * * *`)
- Manual dispatch: `gh workflow run sync-channel-stats.yml`

**Что делает:**
1. Клонирует `noroutine_growth` (скрипты) и `noroutine_posting` (админка)
2. Запускает `fetch_channel_stats.py` → сохраняет в `noroutine_posting/max_channel_stats.json`
3. Коммитит изменения в `noroutine_posting` → деплой через GitHub Pages

**Важно:** Workflow требует токен с правами `repo` и `workflow` для коммита в другой репозиторий. Сейчас используется `GITHUB_TOKEN` (может не хватить прав) — если коммиты не проходят, добавьте Personal Access Token в секреты (`GH_PAT`).

## Отображение в админке

### Виджет "Суммарно просмотров"

Код в `index.html`:

```javascript
async function loadMAXStats() {
    const res = await fetch('max_channel_stats.json');
    if (res.ok) {
        maxStats = await res.json();
        document.getElementById('stat-views').innerText = 
            maxStats.total_views.toLocaleString('ru-RU');
    }
}
```

Вызывается автоматически при открытии админки.

## Будущие улучшения

1. **График динамики просмотров** — Chart.js для визуализации роста аудитории
2. **Топ-5 постов по просмотрам** — таблица с кликабельными ссылками
3. **A/B-тесты заголовков** — сравнение просмотров двух вариантов поста
4. **Историческая БД** — накопление данных за месяцы (сейчас только последние 100 постов)
5. **Alerts** — уведомления, если пост набрал <50 просмотров за 24 часа

## Ограничения MAX Bot API

- **Нет лайков/реакций** — поле `stat` содержит только `views`
- **Нет reach/impressions** — нельзя узнать, скольким людям пост был показан
- **Только последние N постов** — `GET /messages?count=100` возвращает максимум 100 (можно пагинировать через `from`/`to` параметры)

## Troubleshooting

### Виджет показывает 0

1. Проверьте, что `max_channel_stats.json` существует в `noroutine_posting`
2. Откройте DevTools → Console → проверьте ошибки загрузки
3. Убедитесь, что GitHub Pages обновился (может быть задержка 1-2 минуты после коммита)

### Workflow падает с 403

- Нужен токен с правами `repo` и `workflow` в секрете `GH_PAT`
- Или измените workflow: коммитить в `noroutine_growth` и ссылаться на него из админки

### Статистика не обновляется

- Проверьте последний запуск: `gh run list --workflow=sync-channel-stats.yml --repo personalartru/noroutine_growth`
- Посмотрите логи: `gh run view {run_id} --log`
- Убедитесь, что `MAX_BOT_TOKEN` и `MAX_CHANNEL_ID` установлены в секретах
