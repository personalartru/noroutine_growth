"""Лид-магнит и заявки в MAX-канале.

Бот MAX (@noroutine_bot) администратор канала. Запускается в CI-цепочке
и слушает обсуждение канала: если человек подписан на канал и просит
материал — отдаёт ZIP, если пишет задачу — пересылает её владельцу.

Запуск: python max_lead.py [--minutes N]
"""
import base64
import json
import os
import sys
import time

import requests

MAX_API = os.environ.get("MAX_API_BASE", "https://platform-api2.max.ru")
TOKEN = os.environ["MAX_BOT_TOKEN"]
CHANNEL_ID = os.environ["MAX_CHANNEL_ID"]
ADMIN_CHAT_ID = os.environ.get("MAX_ADMIN_CHAT_ID", "")
MATERIALS_PATH = os.environ.get("MATERIALS_PATH", "materials/noroutine-n8n-pack.zip")
RUN_MINUTES = float(os.environ.get("BOT_RUN_MINUTES", "8") or 8)
OFFSET_FILE = os.environ.get("MAX_OFFSET_FILE", ".max_offset")

TEXT_HELLO = (
    "Привет! Это бот канала «No ! Routine» — про автоматизацию рутины "
    "в digital и проектных командах.\n\n"
    "Внутри — 5 готовых n8n-воркфлоу: заявки из форм в Яндекс Трекере, "
    "автоназначение задач, боты обратной связи в Telegram и MAX, выгрузка "
    "в Google Sheets, ежедневные отчёты и приём лидов по REST.\n\n"
    "Материал бесплатный — нужно быть подписчиком канала."
)

TEXT_AFTER_SUB = (
    "Готово, спасибо за подписку! Отправляю сборку шаблонов.\n\n"
    "Если нужна автоматизация под ваш конкретный процесс (а не готовый "
    "шаблон) — напишите, разберу и соберу под вас."
)

TEXT_REQUEST_SENT = (
    "Принял запрос — передал Павел, он свяжется с вами.\n\n"
    "Пока ждёте ответа: посмотрите архив выше — там воркфлоу, которые чаще всего "
    "нужны первыми, и их можно развернуть сразу."
)

BTN_SUB = {"type": "link", "text": "Подписаться на канал", "url": "https://max.ru/channel_noroutine"}
BTN_TASK = {"type": "callback", "text": "Хочу такую же под свой процесс", "action": "want_task"}

TEXT_TASK_PROMPT = (
    "Отлично. Опишите задачу одним сообщением: что сейчас делаете руками, "
    "какими системами пользуетесь и сколько времени это занимает. "
    "Передам Павел — он разберёт и предложит решение."
)


def call(method, path, query=None, body=None):
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


def send_message(chat_id, text, buttons=None):
    body = {"text": text, "format": "html", "notify": True}
    if buttons:
        body["attachments"] = [{
            "type": "inline_keyboard",
            "payload": {"buttons": [buttons]},
        }]
    return call("POST", "messages", query={"chat_id": chat_id}, body=body)


def reply(chat_id, post_id, text, buttons=None):
    """Ответ комментарием к тому же посту, иначе — сообщением в чат."""
    if post_id:
        try:
            call("POST", f"messages/{post_id}/comments", body={
                "text": text,
                "format": "html",
            })
            print("Ответ комментарием к посту:", post_id)
            return True
        except RuntimeError as e:
            print("Не удалось ответить комментарием:", e)
    send_message(chat_id, text, buttons)
    return True


def upload_pack():
    """Два варианта загрузки: сразу с токеном или через upload-URL."""
    with open(MATERIALS_PATH, "rb") as f:
        r = requests.post(
            f"{MAX_API}/uploads",
            params={"type": "file"},
            headers={"Authorization": TOKEN},
            files={"file": (os.path.basename(MATERIALS_PATH), f, "application/zip")},
            timeout=180,
        )
    if r.status_code != 200:
        raise RuntimeError(f"uploads: HTTP {r.status_code} {r.text[:200]}")
    data = r.json()
    token = data.get("token") or (data.get("result") or {}).get("token")
    if token:
        return token

    upload_url = data.get("url")
    if not upload_url:
        raise RuntimeError(f"MAX не вернул токен файла: {str(data)[:200]}")
    with open(MATERIALS_PATH, "rb") as f:
        r2 = requests.post(
            upload_url,
            headers={"Authorization": TOKEN},
            files={"data": (os.path.basename(MATERIALS_PATH), f, "application/zip")},
            timeout=180,
        )
    if r2.status_code != 200:
        raise RuntimeError(f"upload url: HTTP {r2.status_code} {r2.text[:200]}")
    data2 = r2.json()
    token = data2.get("token") or (data2.get("result") or {}).get("token")
    if not token:
        raise RuntimeError(f"MAX не вернул токен файла: {str(data2)[:200]}")
    return token


def send_pack(chat_id):
    token = upload_pack()
    call("POST", "messages", query={"chat_id": chat_id}, body={
        "text": "5 готовых n8n-воркфлоу — импорт в n8n за минуту. Гайд внутри архива.",
        "format": "html",
        "notify": True,
        "attachments": [{"type": "file", "payload": {"token": token}}],
    })


def is_subscribed(user_id):
    """Статус пользователя в канале: подписчик — получит материал."""
    for target in (CHANNEL_ID, f"-{CHANNEL_ID.lstrip('-')}"):
        try:
            member = call("GET", f"chats/{target}/members/{user_id}")
        except RuntimeError:
            continue
        status = (member or {}).get("status")
        return status in ("creator", "administrator", "member", "restricted")
    return None


def forward_to_admin(user_id, name, text):
    link = f"https://max.ru/u/{user_id}" if user_id else ""
    message = (
        "📩 Заявка из MAX-канала\n"
        f"Кто: {name or 'без имени'}\n"
        f"user_id: {user_id}\n"
        f"Ссылка: {link}\n\n"
        f"Текст:\n{text}"
    )
    if not ADMIN_CHAT_ID:
        print("MAX_ADMIN_CHAT_ID не задан — заявка только в лог")
        return False
    try:
        send_message(ADMIN_CHAT_ID, message)
        return True
    except RuntimeError as e:
        print("Не удалось переслать заявку:", e)
        return False


def load_offset():
    try:
        with open(OFFSET_FILE, encoding="utf-8") as f:
            return int(f.read().strip() or 0)
    except (OSError, ValueError):
        return 0


def save_offset(offset):
    try:
        with open(OFFSET_FILE, "w", encoding="utf-8") as f:
            f.write(str(offset))
    except OSError:
        pass


def handle_event(event):
    kind = event.get("update_type") or event.get("type")
    message = event.get("message") or {}
    body = message.get("body") or {}
    text = (body.get("text") or "").strip()
    recipient = message.get("recipient") or {}
    chat_id = recipient.get("chat_id")
    chat_type = recipient.get("chat_type")
    post_id = recipient.get("post_id")
    sender = message.get("sender") or event.get("user") or {}
    user_id = sender.get("user_id")
    name = sender.get("name") or sender.get("first_name") or ""
    print(f"событие {kind} | chat_type {chat_type} | post_id(b64) "
          f"{base64.b64encode(str(post_id).encode()).decode()} | chat_id(b64) "
          f"{base64.b64encode(str(chat_id).encode()).decode()} | "
          f"user {user_id} | текст: {text[:60]!r}")
    if not text:
        return

    lowered = text.lower()
    if lowered in ("/start", "старт", "начать", "материал", "/материал", "связки", "шаблоны"):
        state = is_subscribed(user_id)
        if state:
            reply(chat_id, post_id, TEXT_AFTER_SUB)
            send_pack(chat_id)
            print("Выдан материал:", chat_id)
        else:
            reply(chat_id, post_id, TEXT_HELLO, buttons=BTN_SUB)
        return

    if forward_to_admin(user_id, name, text):
        reply(chat_id, post_id, TEXT_REQUEST_SENT)
    else:
        reply(chat_id, post_id, "Запрос принят, скоро свяжемся.")


def main():
    minutes = RUN_MINUTES
    if "--minutes" in sys.argv:
        minutes = float(sys.argv[sys.argv.index("--minutes") + 1])

    offset = load_offset()
    deadline = time.time() + minutes * 60
    print(f"MAX-лид-бот запущен, offset {offset}, лимит {minutes} мин")

    while time.time() < deadline:
        try:
            data = call("GET", "updates", query={"offset": offset, "timeout": 20, "limit": 100})
        except RuntimeError as e:
            print("Ошибка API:", e)
            time.sleep(3)
            continue
        except requests.exceptions.RequestException as e:
            print("Сеть недоступна:", e)
            time.sleep(5)
            continue

        for event in (data.get("updates") or []):
            offset = max(offset, (event.get("update_id") or 0) + 1)
            save_offset(offset)
            try:
                handle_event(event)
            except Exception as e:
                print("Ошибка обработки события:", e)

    print("Время вышло, offset сохранён:", offset)


if __name__ == "__main__":
    main()
