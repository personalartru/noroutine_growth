#!/usr/bin/env python3
"""
Реактивация подписчиков MAX-канала: отправка личных сообщений неактивным подписчикам.

Стратегия: так как MAX API не предоставляет last_activity_time для подписчиков канала,
используем альтернативный подход:
1. Публикуем специальный пост с кнопкой "Я тут!" (раз в 2 недели)
2. Через 3 дня собираем тех, кто НЕ нажал кнопку
3. Отправляем им личное сообщение с вопросом о контенте
"""

import os
import sys
import time
import json
import requests
from datetime import datetime, timedelta

MAX_BOT_TOKEN = os.environ.get("MAX_BOT_TOKEN")
CHANNEL_ID = os.environ.get("MAX_CHANNEL_ID", "-71062363105923")
ADMIN_CHAT_ID = os.environ.get("MAX_ADMIN_CHAT_ID")

# Кеш: user_id тех, кто нажал кнопку "Я тут!" (за последние 3 дня)
ACTIVE_USERS_FILE = ".max_active_users.json"
# Кеш: диалоги user_id -> chat_id
DIALOGS_FILE = ".max_dialogs.json"


def call(method, path, query=None, body=None):
    """Вызов MAX Bot API."""
    url = f"https://platform-api2.max.ru/{path}"
    headers = {"Authorization": MAX_BOT_TOKEN, "Content-Type": "application/json"}
    r = requests.request(method, url, params=query, json=body, headers=headers, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"{method} {path}: HTTP {r.status_code} {r.text[:200]}")
    return r.json()


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_channel_members(limit=500):
    """Получить подписчиков канала (до limit)."""
    try:
        resp = call("GET", f"chats/{CHANNEL_ID}/members", query={"count": min(limit, 100)})
        members = resp.get("members", [])
        print(f"Получено {len(members)} подписчиков канала")
        return members
    except RuntimeError as e:
        print(f"Ошибка получения подписчиков: {e}")
        return []


def publish_reactivation_post():
    """Опубликовать пост с кнопкой 'Я тут!' для определения активных подписчиков."""
    text = (
        "🔔 Проверка связи!\n\n"
        "Хочу убедиться, что вам интересен контент канала. "
        "Если вы читаете посты и они вам полезны — нажмите кнопку ниже. "
        "Это займёт 1 секунду, но поможет мне понять, что делать дальше.\n\n"
        "Спасибо! 🙏"
    )
    buttons = [[{"type": "callback", "text": "Я тут! 👋", "payload": "im_active"}]]
    body = {
        "chat_id": CHANNEL_ID,
        "text": text,
        "format": "html",
        "notify": True,
        "attachments": [{"type": "inline_keyboard", "payload": {"buttons": buttons}}]
    }
    try:
        resp = call("POST", "messages", body=body)
        post_id = resp.get("message", {}).get("body", {}).get("mid")
        print(f"Пост опубликован: {post_id}")
        return post_id
    except RuntimeError as e:
        print(f"Ошибка публикации поста: {e}")
        return None


def collect_active_users():
    """
    Собрать user_id тех, кто нажал 'im_active' за последние 3 дня.
    (В реальности: обработка callback_query с payload='im_active' в основном боте
    должна сохранять user_id в .max_active_users.json)
    
    Здесь просто читаем файл.
    """
    active = load_json(ACTIVE_USERS_FILE)
    # Очищаем устаревшие записи (старше 14 дней)
    cutoff = time.time() - 14 * 86400
    active = {uid: ts for uid, ts in active.items() if ts > cutoff}
    save_json(ACTIVE_USERS_FILE, active)
    return set(active.keys())


def send_reactivation_message(user_id, chat_id, name):
    """Отправить личное сообщение с вопросом о контенте."""
    text = (
        f"Привет{', ' + name if name else ''}! 👋\n\n"
        "Заметил, что вы давно не взаимодействовали с постами в канале. "
        "Мне важно знать, интересен ли вам контент.\n\n"
        "Напишите, пожалуйста:\n"
        "• Что бы вы хотели видеть в канале?\n"
        "• Какие темы для вас актуальны?\n"
        "• Или просто напишите 'Всё ок', если контент подходит 🙂\n\n"
        "Спасибо за ваше время!"
    )
    buttons = [[
        {"type": "link", "text": "Вернуться в канал", "url": "https://max.ru/channel_noroutine"}
    ]]
    body = {
        "chat_id": chat_id,
        "text": text,
        "format": "html",
        "notify": True,
        "attachments": [{"type": "inline_keyboard", "payload": {"buttons": buttons}}]
    }
    try:
        call("POST", "messages", body=body)
        print(f"Отправлено сообщение реактивации: user_id={user_id}, chat_id={chat_id}")
        return True
    except RuntimeError as e:
        print(f"Не удалось отправить реактивацию ({user_id}): {e}")
        return False


def main():
    if not MAX_BOT_TOKEN:
        print("Ошибка: MAX_BOT_TOKEN не установлен")
        sys.exit(1)

    action = sys.argv[1] if len(sys.argv) > 1 else "reactivate"

    if action == "publish":
        # Шаг 1: опубликовать пост с кнопкой "Я тут!"
        print("Публикую пост для определения активных подписчиков...")
        publish_reactivation_post()
        print("\nГотово! Через 3 дня запустите 'reactivate' для отправки сообщений неактивным.")
        return

    if action == "reactivate":
        # Шаг 2: отправить сообщения тем, кто НЕ нажал кнопку
        print("Собираю активных подписчиков...")
        active_users = collect_active_users()
        print(f"Активных подписчиков (нажали 'Я тут!' за 14 дней): {len(active_users)}")

        print("\nПолучаю список всех подписчиков канала...")
        members = get_channel_members(limit=500)

        dialogs = load_json(DIALOGS_FILE)
        sent = 0
        skipped = 0

        for member in members:
            user_id = str(member.get("user_id"))
            name = member.get("first_name", "")
            is_bot = member.get("is_bot", False)

            if is_bot:
                skipped += 1
                continue

            if user_id in active_users:
                skipped += 1
                continue

            # Пытаемся отправить реактивацию
            chat_id = dialogs.get(user_id)
            if not chat_id:
                print(f"Пропускаю {user_id}: диалог не известен (пользователь не запускал бота)")
                skipped += 1
                continue

            if send_reactivation_message(int(user_id), chat_id, name):
                sent += 1
                time.sleep(1)  # Rate limiting

        print(f"\nГотово! Отправлено сообщений реактивации: {sent}, пропущено: {skipped}")
        if ADMIN_CHAT_ID:
            try:
                call("POST", "messages", body={
                    "chat_id": ADMIN_CHAT_ID,
                    "text": f"✅ Реактивация завершена\n\nОтправлено: {sent}\nПропущено: {skipped}",
                    "format": "html"
                })
            except RuntimeError:
                pass


if __name__ == "__main__":
    main()
