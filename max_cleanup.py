"""Удаляет служебные (диагностические) сообщения из личного чата с ботом в MAX.

Чистит сообщения, которые отправляли проверочные скрипты:
  «Проверка вложения: ...», «Тест: доставка архива админу».

Запуск: python max_cleanup.py
"""
import os

import requests

MAX_API = os.environ.get("MAX_API_BASE", "https://platform-api2.max.ru")
TOKEN = os.environ["MAX_BOT_TOKEN"]
ADMIN_CHAT_ID = os.environ.get("MAX_ADMIN_CHAT_ID", "")

PREFIXES = ("Проверка вложения", "Тест: доставка архива")


def main():
    if not ADMIN_CHAT_ID:
        print("MAX_ADMIN_CHAT_ID не задан — нечего чистить")
        return

    r = requests.get(
        f"{MAX_API}/messages",
        params={"chat_id": ADMIN_CHAT_ID, "limit": 100},
        headers={"Authorization": TOKEN},
        timeout=60,
    )
    if r.status_code != 200:
        print("Не удалось получить историю:", r.status_code, r.text[:200])
        return

    messages = r.json().get("messages") or []
    print("Сообщений в чате:", len(messages))

    removed = 0
    for message in messages:
        body = message.get("body") or {}
        text = (body.get("text") or "").strip()
        if not text.startswith(PREFIXES):
            continue
        mid = body.get("mid")
        d = requests.delete(
            f"{MAX_API}/messages",
            params={"message_id": mid},
            headers={"Authorization": TOKEN},
            timeout=60,
        )
        if d.status_code == 200:
            removed += 1
            print("Удалено:", mid, "|", text[:60])
        else:
            print("Не удалось удалить", mid, "-", d.status_code, d.text[:120])

    print("Итого удалено:", removed)


if __name__ == "__main__":
    main()
