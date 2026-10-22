"""Лид-магнит и заявки в MAX-канале.

Сценарий 1:1 с Telegram-ботом (noroutine_growth/bot.py):
- «/start» → если подписан: «Готово, спасибо за подписку!» + архив с 5 воркфлоу
  и кнопкой «Хочу такую же под свой процесс»;
- если не подписан: приветствие + кнопки «Подписаться на канал» и «Я подписался»;
- кнопка «Я подписался» → проверка подписки и выдача архива;
- кнопка «Хочу такую же под свой процесс» → просьба описать задачу;
- любой другой текст → заявка: владельцу уходит уведомление с данными
  пользователя, пользователю в личку — «Принял запрос — изучаю и скоро свяжусь
  с вами.» вместе с архивом.

Особенности MAX: бот пишет только тем, кто его запустил, поэтому если личка
недоступна, в чат обсуждения уходит кнопка-диплинк «Открыть бота».

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
RUN_MINUTES = float(os.environ.get("BOT_RUN_MINUTES", "9") or 9)
OFFSET_FILE = os.environ.get("MAX_OFFSET_FILE", ".max_offset")
PENDING_FILE = os.environ.get("MAX_PENDING_FILE", ".max_pending.json")
COMMENT_CHAT_FILE = os.environ.get("MAX_COMMENT_CHAT_FILE", ".max_comment_chat")
DIALOGS_FILE = os.environ.get("MAX_DIALOGS_FILE", ".max_dialogs.json")
BOT_USERNAME = os.environ.get("MAX_BOT_USERNAME", "")

# ── Тексты (совпадают с Telegram-ботом) ──────────────────────────────────────
TEXT_HELLO = (
    "Привет! Это бот канала «No ! Routine» — про автоматизацию рутины в "
    "проектном управлении и digital.\n\n"
    "Внутри — 5 готовых n8n-воркфлоу, которые закрывают типовую рутину:\n"
    "заявки из форм, задачи в Яндекс Трекере, статусы, AI-комментарии, "
    "выгрузка в Google Sheets, боты обратной связи в Telegram и MAX, "
    "ежедневные отчёты и приём лидов по REST.\n\n"
    "Материал бесплатный — нужно только быть подписанным на канал."
)

TEXT_AFTER_SUB = (
    "Готово, спасибо за подписку! Отправляю сборку шаблонов.\n\n"
    "Если нужна автоматизация под ваш конкретный процесс (а не готовый шаблон) — "
    "напишите, разберу и соберу под вас."
)

TEXT_REQUEST_SENT = (
    "Принял запрос — изучаю и скоро свяжусь с вами.\n\n"
    "Пока ждёте ответа: посмотрите архив выше — там воркфлоу, которые чаще всего "
    "нужны первыми для автоматизации процессов, и их можно развернуть сразу."
)

TEXT_TASK_PROMPT = (
    "Отлично.! Опишите задачу одним сообщением: что сейчас делаете руками, "
    "какими системами пользуетесь и сколько времени это занимает. "
    "Я изучу ваш запрос и предложу решение."
)

TEXT_PACK = "5 готовых n8n-воркфлоу — импорт в n8n за минуту. Гайд внутри архива."

TEXT_SUBSCRIBE_HINT = "Подпишись на канал — и сразу пришлю сборку воркфлоу."
TEXT_NOT_SUBSCRIBED = "Подписка пока не видна. Подпишитесь и нажмите ещё раз."

# ── Кнопки ───────────────────────────────────────────────────────────────────
BTN_SUB = {"type": "link", "text": "Подписаться на канал", "url": "https://max.ru/channel_noroutine"}
BTN_CHECK = {"type": "callback", "text": "Я подписался", "payload": "check_sub"}
BTN_TASK = {"type": "callback", "text": "Хочу такую же под свой процесс", "payload": "want_task"}
BTN_CHANNEL = {"type": "link", "text": "Канал в MAX", "url": "https://max.ru/channel_noroutine"}


def bot_username():
    """Юзернейм бота для диплинков (технический, как в /me)."""
    global BOT_USERNAME
    if not BOT_USERNAME:
        try:
            BOT_USERNAME = (call("GET", "me") or {}).get("username") or ""
        except RuntimeError:
            BOT_USERNAME = "noroutine_bot"
    return BOT_USERNAME


def bot_display_name():
    """Отображаемое имя бота (без @ — упоминания в комментариях запрещены)."""
    try:
        me = call("GET", "me") or {}
        return (me.get("name") or me.get("first_name") or bot_username()).lstrip("@")
    except RuntimeError:
        return bot_username()


def bot_link(payload=""):
    link = f"https://max.ru/{bot_username()}"
    return f"{link}?start={payload}" if payload else link


def open_bot_button():
    return {"type": "link", "text": "Открыть бота и забрать архив", "url": bot_link("lead")}


# ── API ──────────────────────────────────────────────────────────────────────
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


def send_direct(user_id, text, file_token=None, buttons=None, fallback_chat_id=None,
                chat_id=None):
    """Личное сообщение пользователю.

    В MAX chat_id диалога НЕ равен user_id: писать нужно на chat_id
    (recipient.chat_id в событии), иначе 404 chat.not.found.
    """
    user_id = chat_id or user_id
    body = {"text": text, "format": "html", "notify": True}
    attachments = []
    if file_token:
        attachments.append({"type": "file", "payload": {"token": file_token}})
    if buttons:
        attachments.append({"type": "inline_keyboard", "payload": {"buttons": buttons}})
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


def send_to_chat(chat_id, text, buttons=None):
    """Запасной вариант: сообщение в чат обсуждения (в канал не пишем)."""
    try:
        body = {"text": text, "format": "html", "notify": True}
        if buttons:
            body["attachments"] = [{"type": "inline_keyboard", "payload": {"buttons": buttons}}]
        call("POST", "messages", query={"chat_id": chat_id}, body=body)
        print("Ответ в чат обсуждения:", chat_id)
        return True
    except RuntimeError as e:
        print("Не удалось ответить в чат:", e)
        return False


def send_comment(post_id, text):
    """Ответ комментарием под постом.

    Комментарии в MAX живут внутри канала: публикация в chat_id канала
    создала бы пост для всех. Ответ на комментарий — только
    POST /messages/{postId}/comments. Вложения в комментариях не поддерживаются.
    """
    safe_text = text.replace("@", " ")
    try:
        call("POST", f"messages/{post_id}/comments",
             body={"text": safe_text, "format": "html"})
        print("Комментарий отправлен:", post_id)
        return True
    except RuntimeError as e:
        print("Не удалось отправить комментарий:", e)
        return False


def answer_callback(callback_id, text):
    """Ответ на нажатие кнопки: POST /answers?callback_id=..."""
    try:
        call("POST", "answers", query={"callback_id": callback_id},
             body={"message": {"text": text, "format": "html"}})
        return True
    except RuntimeError as e:
        print("Не удалось ответить на callback:", e)
        return False


def respond(user_id, chat_id, post_id, chat_type, text, file_token=None, buttons=None):
    """Ответ пользователю: сначала личка, иначе комментарий под постом.

    chat_id — адресат для лички (chat_id диалога, если он известен).
    В канал (chat_type == "channel") ничего не отправляем — это публикация
    поста для всех подписчиков.
    """
    if buttons:
        buttons = list(buttons) + [[BTN_CHANNEL]]
    if chat_id and send_direct(user_id, text, file_token=file_token, buttons=buttons,
                               chat_id=chat_id):
        return True

    if post_id:
        bridge = (
            "\n\nЧтобы получить архив с 5 n8n-воркфлоу и ответ по вашей задаче — "
            f"откройте бота {bot_display_name()} в поиске MAX и напишите /start. "
            f"Прямая ссылка: {bot_link('lead')}"
        )
        return send_comment(post_id, text + bridge)

    if chat_type == "channel":
        print("Пропускаю ответ: это канал, постинг из лид-бота запрещён")
        return False

    return send_to_chat(chat_id, text, buttons)


def upload_pack():
    """Загрузка файла в MAX: два шага.

    1) POST /uploads?type=file -> {"url": ...}
    2) POST файла на этот url (multipart, поле data) -> {"fileId", "token"}
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


def deliver_material(user_id, source=None, chat_id=None, post_id=None, chat_type=None):
    """Выдаёт архив: в личку, при неудаче — комментарием с мостом к боту."""
    token = upload_pack()
    ok = respond(user_id, chat_id, post_id, chat_type, TEXT_PACK,
                 file_token=token, buttons=[[BTN_TASK]])
    if ok:
        print("Архив выдан:", user_id)
    if ADMIN_CHAT_ID:
        send_direct(ADMIN_CHAT_ID, f"Лид-магнит забрали: user_id={user_id}, "
                                   f"источник={source or 'unknown'}")
    return ok


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


# ── Состояние ────────────────────────────────────────────────────────────────
def load_pending():
    try:
        with open(PENDING_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_pending(pending):
    try:
        with open(PENDING_FILE, "w", encoding="utf-8") as f:
            json.dump(pending, f, ensure_ascii=False, indent=2)
    except OSError as e:
        print("Не удалось сохранить состояние заявок:", e)


def code_sha():
    """Версия кода (sha) — чтобы по логу видеть, какая версия работает."""
    import subprocess
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, timeout=10).stdout.strip() or "?"
    except Exception:
        return "?"


def load_dialogs():
    try:
        with open(DIALOGS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_dialogs(dialogs):
    try:
        with open(DIALOGS_FILE, "w", encoding="utf-8") as f:
            json.dump(dialogs, f, ensure_ascii=False, indent=2)
    except OSError as e:
        print("Не удалось сохранить диалоги:", e)


def remember_dialog(user_id, chat_id):
    """В MAX chat_id диалога не равен user_id — запоминаем соответствие."""
    if not user_id or not chat_id:
        return
    dialogs = load_dialogs()
    if dialogs.get(str(user_id)) != chat_id:
        dialogs[str(user_id)] = chat_id
        save_dialogs(dialogs)
        print("Запомнил диалог:", user_id, "->", chat_id)


def dialog_for(user_id):
    """chat_id личного диалога с пользователем (если бот его уже получал)."""
    return load_dialogs().get(str(user_id))


def remember_comment_chat(chat_id):
    """Запоминаем чат обсуждений канала: туда бот отвечает, если личка недоступна."""
    try:
        with open(COMMENT_CHAT_FILE, "w", encoding="utf-8") as f:
            f.write(str(chat_id))
    except OSError as e:
        print("Не удалось сохранить чат обсуждений:", e)


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


# ── Обработчики ─────────────────────────────────────────────────────────────
def handle_start(user_id, chat_id, post_id, chat_type, text):
    pending = load_pending()
    request = pending.pop(str(user_id), None)
    save_pending(pending)

    state = is_subscribed(user_id)
    if state:
        respond(user_id, chat_id, post_id, chat_type, TEXT_AFTER_SUB)
        deliver_material(user_id, "max", chat_id, post_id)
        return
    respond(user_id, chat_id, post_id, chat_type,
            TEXT_HELLO + "\n\n" + TEXT_SUBSCRIBE_HINT,
            buttons=[[BTN_SUB], [BTN_CHECK]])


def handle_callback(callback):
    payload = callback.get("payload") or ""
    callback_id = callback.get("callback_id")
    user = callback.get("user") or {}
    user_id = user.get("user_id")

    chat_id = dialog_for(user_id) or user_id

    if payload == "want_task":
        if not send_direct(user_id, TEXT_TASK_PROMPT, buttons=[[BTN_CHANNEL]],
                           chat_id=chat_id):
            answer_callback(callback_id, TEXT_TASK_PROMPT)
        return

    if payload == "check_sub":
        if is_subscribed(user_id):
            answer_callback(callback_id, TEXT_AFTER_SUB)
            deliver_material(user_id, "bot-check", chat_id, None, "dialog")
        else:
            answer_callback(callback_id, TEXT_NOT_SUBSCRIBED)
        return


def handle_text(user_id, chat_id, post_id, chat_type, name, username, text):
    lowered = text.lower()
    if lowered in ("/start", "старт", "начать", "/material", "/материал",
                   "/materials", "/пакет", "материал", "связки", "шаблоны", "воркфлоу"):
        handle_start(user_id, chat_id, post_id, chat_type, text)
        return

    if lowered in ("/help", "/помощь", "помощь"):
        respond(user_id, chat_id, post_id, chat_type, TEXT_HELLO)
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
        respond(user_id, chat_id, post_id, chat_type, TEXT_REQUEST_SENT,
                file_token=token)
    else:
        respond(user_id, chat_id, post_id, chat_type,
                "Запрос принят, скоро свяжемся. Для сбора шаблонов пришлите /start.")


def handle_bot_started(event):
    """Пользователь открыл бота по диплинку: отдаём архив в личку."""
    user = event.get("user") or {}
    user_id = user.get("user_id")
    chat_id = event.get("chat_id") or dialog_for(user_id) or user_id
    remember_dialog(user_id, chat_id)
    print("bot_started | user", user_id, "| chat", chat_id, "| payload", event.get("payload"))

    pending = load_pending()
    request = pending.pop(str(user_id), None)
    save_pending(pending)

    send_direct(user_id, TEXT_AFTER_SUB, buttons=[[BTN_CHANNEL]], chat_id=chat_id)
    deliver_material(user_id, "deep-link", chat_id, None, "dialog")


def handle_event(event):
    kind = event.get("update_type") or event.get("type")

    if kind == "bot_started":
        handle_bot_started(event)
        return

    if kind == "message_callback":
        callback = event.get("callback") or {}
        print("событие message_callback | payload", callback.get("payload"),
              "| user", (callback.get("user") or {}).get("user_id"))
        handle_callback(callback)
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

    if chat_type == "dialog" and chat_id:
        remember_dialog(user_id, chat_id)
    if post_id and chat_type == "chat":
        remember_comment_chat(chat_id)
    print(f"событие {kind} | chat_type {chat_type} | user {user_id} | "
          f"chat_id(b64) {base64.b64encode(str(chat_id).encode()).decode()} | "
          f"текст: {text[:60]!r}")
    if not text:
        return
    target = chat_id if chat_type == "dialog" else dialog_for(user_id)
    handle_text(user_id, target, post_id, chat_type, name, username, text)


def main():
    minutes = RUN_MINUTES
    if "--minutes" in sys.argv:
        minutes = float(sys.argv[sys.argv.index("--minutes") + 1])

    offset = load_offset()
    deadline = time.time() + minutes * 60
    print(f"MAX-лид-бот запущен (версия {code_sha()}), offset {offset}, лимит {minutes} мин")

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
