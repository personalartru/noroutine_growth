"""Лид-магнит и заявки в MAX-канале.

Бот MAX (@noroutine_bot) — администратор канала max.ru/channel_noroutine.
Запускается в CI-цепочке и слушает обсуждение канала:

- «/start» / «материал» → если человек подписан на канал, бот отдаёт ZIP
  с 5 n8n-воркфлоу в личку; если нет — просит подписаться (кнопка);
- любой другой текст → заявка: владельцу уходит уведомление с данными
  пользователя, пользователю в личку — подтверждение и архив.
  В канале бот не пишет никогда.

Запуск: python max_lead.py [--minutes N]
"""
import base64
import os
import sys
import time

import requests

MAX_API = os.environ.get("MAX_API_BASE", "https://platform-api2.max.ru")
TOKEN = os.environ["MAX_BOT_TOKEN"]
CHANNEL_ID = os.environ["MAX_CHANNEL_ID"]
ADMIN_CHAT_ID = os.environ.get("MAX_ADMIN_CHAT_ID", "")
MATERIALS_PATH = os.environ.get("MATERIALS_PATH", "materials/noroutine-n8n-pack.zip")
RUN_MINUTES = float(os.environ.get("BOT_RUN_MINUTES", "16") or 16)
OFFSET_FILE = os.environ.get("MAX_OFFSET_FILE", ".max_offset")
PENDING_FILE = os.environ.get("MAX_PENDING_FILE", ".max_pending.json")
BOT_USERNAME = os.environ.get("MAX_BOT_USERNAME", "")

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
    "Принял запрос и скоро мы с вами свяжемся!\n\n"
    "Пока ждёте ответа: посмотрите архив — там воркфлоу для n8n, которые чаще "
    "всего нужны первыми, и их можно развернуть сразу."
)

TEXT_OPEN_BOT = "Откройте бота, чтобы получить архив и ответ по запросу 👇"

TEXT_PACK = "5 готовых n8n-воркфлоу — импорт в n8n за минуту. Гайд внутри архива."

BTN_SUB = {"type": "link", "text": "Подписаться на канал", "url": "https://max.ru/channel_noroutine"}


def bot_username():
    """Юзернейм бота для диплинков (технический, как в /me)."""
    global BOT_USERNAME
    if not BOT_USERNAME:
        try:
            BOT_USERNAME = (call("GET", "me") or {}).get("username") or ""
        except RuntimeError:
            BOT_USERNAME = "noroutine_bot"
    return BOT_USERNAME


def bot_link(payload=""):
    link = f"https://max.ru/{bot_username()}"
    return f"{link}?start={payload}" if payload else link


def open_bot_button():
    return {"type": "link", "text": "Открыть бота и забрать архив", "url": bot_link("lead")}


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


def send_direct(user_id, text, file_token=None, buttons=None, fallback_chat_id=None):
    """Личное сообщение пользователю: в MAX chat_id диалога = user_id."""
    body = {"text": text, "format": "html", "notify": True}
    attachments = []
    if file_token:
        attachments.append({"type": "file", "payload": {"token": file_token}})
    if buttons:
        attachments.append({"type": "inline_keyboard", "payload": {"buttons": [buttons]}})
    if attachments:
        body["attachments"] = attachments

    targets = [user_id]
    if fallback_chat_id and fallback_chat_id != user_id:
        targets.append(fallback_chat_id)
    for target in targets:
        try:
            call("POST", "messages", query={"chat_id": target}, body=body)
            print("Отправлено в личку:", target)
            return True
        except RuntimeError as e:
            print(f"Личка недоступна ({target}):", e)
    return False


def notify_in_chat(chat_id, text, buttons=None):
    """Запасной вариант: сообщение в чат обсуждения (в канал не пишем)."""
    try:
        body = {"text": text, "format": "html", "notify": True}
        if buttons:
            body["attachments"] = [{"type": "inline_keyboard", "payload": {"buttons": [buttons]}}]
        call("POST", "messages", query={"chat_id": chat_id}, body=body)
        print("Ответ в чат обсуждения:", chat_id)
        return True
    except RuntimeError as e:
        print("Не удалось ответить в чат:", e)
        return False


def upload_pack():
    """Загрузка файла в MAX: два шага (проверено на живом API).

    1) POST /uploads?type=file -> {"url": ...}
    2) POST файла на этот url (multipart, поле data) -> {"fileId", "token"}
    Токен из шага 2 подставляется в attachments.payload.token.
    """
    r = requests.post(f"{MAX_API}/uploads", params={"type": "file"},
                      headers={"Authorization": TOKEN}, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"uploads: HTTP {r.status_code} {r.text[:200]}")
    data = r.json()
    token = data.get("token") or (data.get("result") or {}).get("token")
    if token:
        return token

    upload_url = data.get("url")
    if not upload_url:
        raise RuntimeError(f"MAX не вернул url для загрузки: {str(data)[:200]}")

    with open(MATERIALS_PATH, "rb") as f:
        r2 = requests.post(upload_url, headers={"Authorization": TOKEN},
                           files={"data": (os.path.basename(MATERIALS_PATH), f, "application/zip")},
                           timeout=180)
    if r2.status_code != 200:
        raise RuntimeError(f"upload url: HTTP {r2.status_code} {r2.text[:200]}")
    data2 = r2.json()
    token = (data2.get("token") or (data2.get("result") or {}).get("token")
             or data.get("token") or (data.get("result") or {}).get("token"))
    if not token:
        raise RuntimeError(f"MAX не вернул токен файла: {str(data2)[:200]}")
    return token


def send_pack(user_id, chat_id=None):
    """Выдаёт архив: сперва в личку, при неудаче — в чат обсуждения."""
    token = upload_pack()
    if send_direct(user_id, TEXT_PACK, file_token=token, fallback_chat_id=chat_id):
        return True
    if chat_id:
        try:
            call("POST", "messages", query={"chat_id": chat_id}, body={
                "text": TEXT_PACK,
                "format": "html",
                "notify": True,
                "attachments": [{"type": "file", "payload": {"token": token}}],
            })
            print("Архив отправлен в чат:", chat_id)
            return True
        except RuntimeError as e:
            print("Не удалось отдать архив:", e)
    return False


def is_subscribed(user_id):
    """Статус пользователя в канале: подписчик получит материал."""
    for target in (CHANNEL_ID, f"-{CHANNEL_ID.lstrip('-')}"):
        try:
            member = call("GET", f"chats/{target}/members/{user_id}")
        except RuntimeError:
            continue
        status = (member or {}).get("status")
        return status in ("creator", "administrator", "member", "restricted")
    return None


def forward_to_admin(user_id, name, text, username=None):
    """Уведомление владельцу: кто, id, профиль и текст запроса."""
    who = name or "без имени"
    if username:
        who += f" (@{username})"
    message = (
        "📩 Заявка из MAX-канала\n"
        f"Кто: {who}\n"
        f"user_id: {user_id}\n"
        f"Ссылка на профиль: https://max.ru/u/{user_id}\n\n"
        f"Текст запроса:\n{text}\n\n"
        "Ответьте ему в личку MAX: откройте профиль и напишите."
    )
    if not ADMIN_CHAT_ID:
        print("MAX_ADMIN_CHAT_ID не задан — заявка только в лог")
        return False
    try:
        call("POST", "messages", query={"chat_id": ADMIN_CHAT_ID},
             body={"text": message, "format": "html", "notify": True})
        print("Заявка отправлена владельцу")
        return True
    except RuntimeError as e:
        print("Не удалось переслать заявку:", e)
        return False


def load_pending():
    import json as _json
    try:
        with open(PENDING_FILE, encoding="utf-8") as f:
            return _json.load(f)
    except (OSError, ValueError):
        return {}


def save_pending(pending):
    import json as _json
    try:
        with open(PENDING_FILE, "w", encoding="utf-8") as f:
            _json.dump(pending, f, ensure_ascii=False, indent=2)
    except OSError as e:
        print("Не удалось сохранить состояние заявок:", e)


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


def handle_bot_started(event):
    """Пользователь открыл бота по диплинку: отдаём архив в личку."""
    user = event.get("user") or {}
    user_id = user.get("user_id")
    chat_id = event.get("chat_id") or user_id
    payload = event.get("payload")
    print("bot_started | user", user_id, "| payload", payload)

    pending = load_pending()
    request = pending.pop(str(user_id), None)
    save_pending(pending)

    if request:
        send_direct(user_id, TEXT_REQUEST_SENT, fallback_chat_id=chat_id)
        send_pack(user_id, chat_id)
    else:
        send_direct(user_id, TEXT_AFTER_SUB, fallback_chat_id=chat_id)
        send_pack(user_id, chat_id)


def handle_event(event):
    kind = event.get("update_type") or event.get("type")
    if kind == "bot_started":
        handle_bot_started(event)
        return
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
    username = sender.get("username")

    print(f"событие {kind} | chat_type {chat_type} | user {user_id} | "
          f"post_id(b64) {base64.b64encode(str(post_id).encode()).decode()} | "
          f"текст: {text[:60]!r}")
    if not text:
        return

    lowered = text.lower()
    if lowered in ("/start", "старт", "начать", "материал", "/материал", "связки", "шаблоны", "воркфлоу"):
        pending = load_pending()
        request = pending.pop(str(user_id), None)
        save_pending(pending)
        if is_subscribed(user_id):
            send_direct(user_id, TEXT_AFTER_SUB)
            send_pack(user_id, chat_id)
        elif not send_direct(user_id, TEXT_HELLO, buttons=BTN_SUB):
            notify_in_chat(chat_id, TEXT_HELLO, buttons=BTN_SUB)
        return

    if forward_to_admin(user_id, name, text, username):
        pending = load_pending()
        pending[str(user_id)] = {"text": text, "name": name, "username": username}
        save_pending(pending)

        token = None
        try:
            token = upload_pack()
        except RuntimeError as e:
            print("Не удалось загрузить архив:", e)

        if not send_direct(user_id, TEXT_REQUEST_SENT, file_token=token):
            # личка недоступна: пользователь не запускал бота.
            # Оставляем кнопку с диплинком — жмёт и попадает в диалог.
            print("Личка недоступна, предлагаю открыть бота")
            notify_in_chat(chat_id, TEXT_OPEN_BOT, buttons=open_bot_button())
    else:
        send_direct(user_id, "Запрос принят, скоро свяжемся.")


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
