"""Удаляет сообщения лид-бота, случайно опубликованные в канале как посты.

Комментарии в MAX живут внутри канала, поэтому отправка в chat_id канала
создаёт пост для всех. Такие посты надо убрать.

Запуск: python max_cleanup.py [--dry-run]
"""
import os
import sys

import requests

MAX_API = os.environ.get("MAX_API_BASE", "https://platform-api2.max.ru")
TOKEN = os.environ["MAX_BOT_TOKEN"]
CHANNEL_ID = os.environ["MAX_CHANNEL_ID"]

MARKERS = (
    "Принял запрос",
    "Откройте бота",
    "5 готовых n8n-воркфлоу",
    "Готово, спасибо за подписку",
    "Привет! Это бот канала",
    "Материал доступен подписчикам",
)


def api(method, path, query=None, body=None):
    r = requests.request(
        method,
        f"{MAX_API}/{path}",
        params=query,
        headers={"Authorization": TOKEN, "Content-Type": "application/json"},
        json=body,
        timeout=90,
    )
    if r.status_code != 200:
        raise RuntimeError(f"{method} {path}: HTTP {r.status_code} {r.text[:200]}")
    return r.json()


def main():
    dry_run = "--dry-run" in sys.argv
    data = api("GET", "messages", query={"chat_id": CHANNEL_ID})
    messages = data.get("messages") or []
    print("Сообщений в канале:", len(messages))

    removed = 0
    for message in messages:
        body = message.get("body") or {}
        text = body.get("text") or ""
        if not any(marker in text for marker in MARKERS):
            continue
        mid = body.get("mid")
        print(f"  найдено лид-сообщение: {mid} | {text[:70]!r}")
        if dry_run:
            continue
        try:
            api("DELETE", f"messages/{mid}")
            print("    удалено")
            removed += 1
        except RuntimeError as e:
            print("    не удалось удалить:", e)

    print("Удалено:", removed, "| dry-run" if dry_run else "")


if __name__ == "__main__":
    main()
