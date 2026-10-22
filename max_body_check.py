"""Проверка форм тела POST /messages в MAX (диагностика кнопок).

Проверяем, какие варианты тела принимает API, отправляя тестовые сообщения
в личный чат администратора (в канал не пишем).

Запуск: python max_body_check.py
"""
import os

import requests

MAX_API = os.environ.get("MAX_API_BASE", "https://platform-api2.max.ru")
TOKEN = os.environ["MAX_BOT_TOKEN"]
ADMIN_CHAT_ID = os.environ.get("MAX_ADMIN_CHAT_ID", "")

LINK = {"type": "link", "text": "Открыть", "url": "https://max.ru/channel_noroutine"}
CALLBACK = {"type": "callback", "text": "Я подписался", "payload": "check_sub"}

VARIANTS = [
    ("текст+html", {"text": "Проверка 1", "format": "html"}),
    ("текст+html+notify", {"text": "Проверка 2", "format": "html", "notify": True}),
    ("клавиатура 2D [[link]]", {"text": "Проверка 3", "format": "html", "attachments": [
        {"type": "inline_keyboard", "payload": {"buttons": [[LINK]]}}]}),
    ("клавиатура 2D [[callback]]", {"text": "Проверка 4", "format": "html", "attachments": [
        {"type": "inline_keyboard", "payload": {"buttons": [[CALLBACK]]}}]}),
    ("клавиатура 1D [link] (как было)", {"text": "Проверка 5", "format": "html", "attachments": [
        {"type": "inline_keyboard", "payload": {"buttons": [LINK]}}]}),
    ("файл+клавиатура", {"text": "Проверка 6", "format": "html", "attachments": [
        {"type": "inline_keyboard", "payload": {"buttons": [[LINK]]}}]}),
]


def main():
    if not ADMIN_CHAT_ID:
        print("MAX_ADMIN_CHAT_ID не задан — не знаю, куда слать проверку.")
        return
    for name, body in VARIANTS:
        r = requests.post(
            f"{MAX_API}/messages",
            params={"chat_id": ADMIN_CHAT_ID},
            headers={"Authorization": TOKEN, "Content-Type": "application/json"},
            json=body,
            timeout=60,
        )
        ok = "OK " if r.status_code == 200 else "ОШИБКА"
        print(f"{ok} | {name:32} | HTTP {r.status_code} | {r.text[:150]}")


if __name__ == "__main__":
    main()
