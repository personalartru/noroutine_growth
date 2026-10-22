"""Удаляет служебные (диагностические) сообщения из личного чата с ботом в MAX.

Чистит сообщения, которые отправляли проверочные скрипты:
  «Проверка вложения: ...», «Тест: доставка архива админу».

История листается по времени (параметры count/from/to у GET /messages),
поэтому находятся и старые сообщения.

Запуск: python max_cleanup.py
"""
import os

import requests

MAX_API = os.environ.get("MAX_API_BASE", "https://platform-api2.max.ru")
TOKEN = os.environ["MAX_BOT_TOKEN"]
ADMIN_CHAT_ID = os.environ.get("MAX_ADMIN_CHAT_ID", "")

PREFIXES = ("Проверка вложения", "Тест: доставка архива")
MAX_PAGES = 10


def api_get(params):
    return requests.get(
        f"{MAX_API}/messages",
        params=params,
        headers={"Authorization": TOKEN},
        timeout=60,
    )


def api_delete(message_id):
    return requests.delete(
        f"{MAX_API}/messages",
        params={"message_id": message_id},
        headers={"Authorization": TOKEN},
        timeout=60,
    )


def main():
    if not ADMIN_CHAT_ID:
        print("MAX_ADMIN_CHAT_ID не задан — нечего чистить")
        return

    removed = 0
    scanned = 0
    from_param = None
    last_oldest = None

    for page in range(MAX_PAGES):
        # В MAX: from — «время, до которого берём сообщения» (старые),
        # to — «начиная с этого» (новые). Чтобы идти вглубь истории, снижаем from.
        params = {"chat_id": ADMIN_CHAT_ID, "count": 100}
        if from_param is not None:
            params["from"] = from_param
        r = api_get(params)
        if r.status_code != 200:
            print("Не удалось получить историю:", r.status_code, r.text[:200])
            return

        messages = r.json().get("messages") or []
        if not messages:
            print(f"Страница {page + 1}: пусто, всё просмотрено")
            break

        scanned += len(messages)
        for message in messages:
            body = message.get("body") or {}
            text = (body.get("text") or "").strip()
            if not text.startswith(PREFIXES):
                continue
            mid = body.get("mid")
            d = api_delete(mid)
            if d.status_code == 200:
                removed += 1
            else:
                print("Не удалось удалить", mid, "-", d.status_code, d.text[:100])

        timestamps = [m.get("timestamp") for m in messages if m.get("timestamp")]
        if not timestamps:
            break
        oldest = min(timestamps)
        if oldest <= 0 or oldest == last_oldest:
            print("Дальше идти некуда — история кончилась")
            break
        last_oldest = oldest
        from_param = oldest - 1
        print(f"Страница {page + 1}: просмотрено {len(messages)}, идём глубже (from={from_param})")

    print(f"Просмотрено сообщений: {scanned}, удалено служебных: {removed}")


if __name__ == "__main__":
    main()
