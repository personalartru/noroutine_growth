"""Бот выдачи лид-магнита для Telegram-канала @noroutine2026.

Логика: человек жмёт кнопку -> бот проверяет подписку на канал -> отдаёт ZIP
с n8n-шаблонами и пишет событие в лог. Источник перехода фиксируется из
deep link (?start=site|rutube|youtube|...), поэтому видно, какой канал приводит
подписчиков.

Запуск:  python bot.py
Конфиг:  переменные окружения (см. .env.example)
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

import requests

API = "https://api.telegram.org/bot{token}/{method}"
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHANNEL_USERNAME = os.environ.get("CHANNEL_USERNAME", "@noroutine2026")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "")
MATERIALS_PATH = os.environ.get("MATERIALS_PATH", "materials/noroutine-n8n-pack.zip")
EVENTS_LOG = os.environ.get("EVENTS_LOG", "events.jsonl")
POLL_TIMEOUT = int(os.environ.get("POLL_TIMEOUT", "25"))
OFFSET_FILE = os.environ.get("OFFSET_FILE", ".offset")
RUN_MINUTES = float(os.environ.get("BOT_RUN_MINUTES", "0") or 0)

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
    "Если нужна связка под ваш конкретный процесс (а не готовый шаблон) — "
    "напишите, разберу и соберу под вас."
)

BTN_SUB = {"text": "Подписаться на канал", "url": f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}"}
BTN_CHECK = {"text": "Я подписался", "callback_data": "check_sub"}


def api(method, **payload):
    payload = {k: v for k, v in payload.items() if v is not None}
    r = requests.post(API.format(token=TOKEN, method=method), json=payload, timeout=70)
    if r.status_code != 200:
        raise RuntimeError(f"{method}: HTTP {r.status_code} {r.text[:200]}")
    return r.json().get("result")


def send_message(chat_id, text, buttons=None, disable_web_page_preview=True):
    markup = None
    if buttons:
        markup = {"inline_keyboard": [buttons]}
    return api("sendMessage", chat_id=chat_id, text=text, reply_markup=markup,
               disable_web_page_preview=disable_web_page_preview)


def send_document(chat_id, path, caption):
    with open(path, "rb") as f:
        r = requests.post(
            API.format(token=TOKEN, method="sendDocument"),
            data={"chat_id": chat_id, "caption": caption},
            files={"document": (os.path.basename(path), f, "application/zip")},
            timeout=180,
        )
    if r.status_code != 200:
        raise RuntimeError(f"sendDocument: HTTP {r.status_code} {r.text[:200]}")
    return r.json().get("result")


def log_event(**fields):
    fields["ts"] = datetime.now(timezone.utc).isoformat()
    with open(EVENTS_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(fields, ensure_ascii=False) + "\n")


LAST_CHECK_ERROR = ""


def is_subscribed(user_id):
    global LAST_CHECK_ERROR
    target = CHANNEL_ID or CHANNEL_USERNAME
    try:
        member = api("getChatMember", chat_id=target, user_id=user_id)
    except RuntimeError as e:
        LAST_CHECK_ERROR = str(e)
        print("Не удалось проверить подписку:", e)
        return None
    LAST_CHECK_ERROR = ""
    status = member.get("status")
    return status in ("creator", "administrator", "member", "restricted")


def deliver_material(chat_id, source=None):
    send_document(
        chat_id,
        MATERIALS_PATH,
        "5 готовых n8n-воркфлоу — импорт в n8n за минуту. Гайд внутри архива.",
    )
    log_event(event="material_delivered", chat_id=chat_id, source=source)
    if ADMIN_CHAT_ID:
        send_message(
            ADMIN_CHAT_ID,
            f"Лид-магнит забрали: chat_id={chat_id}, источник={source or 'unknown'}",
        )


def handle_start(message):
    chat_id = message["chat"]["id"]
    user = message.get("from", {})
    payload = (message.get("text") or "").split(None, 1)
    source = payload[1] if len(payload) > 1 else "direct"
    log_event(event="start", chat_id=chat_id, user_id=user.get("id"),
              username=user.get("username"), source=source)

    state = is_subscribed(user.get("id"))
    if state is None:
        send_message(chat_id, TEXT_HELLO, buttons=[BTN_SUB, BTN_CHECK])
        return
    if state:
        send_message(chat_id, TEXT_AFTER_SUB)
        deliver_material(chat_id, source)
    else:
        hint = ""
        if state is None:
            hint = ("\n\n⚠️ Сейчас я не могу проверить подписку: бот не администратор "
                    "канала. Если вы — владелец канала, добавьте бота администратором "
                    "и напишите мне ещё раз.")
        send_message(
            chat_id,
            TEXT_HELLO + "\n\nПодпишись на канал — и сразу пришлю сборку воркфлоу." + hint,
            buttons=[BTN_SUB, BTN_CHECK],
        )


def handle_callback(callback):
    chat_id = callback["message"]["chat"]["id"]
    user_id = callback["from"]["id"]
    if callback.get("data") == "check_sub":
        state = is_subscribed(user_id)
        if state:
            api("editMessageText", chat_id=chat_id, message_id=callback["message"]["message_id"],
                text=TEXT_AFTER_SUB)
            deliver_material(chat_id, "bot-check")
        else:
            api("answerCallbackQuery", callback_query_id=callback["id"],
                text="Подписка пока не видна. Подпишитесь и нажмите ещё раз.",
                show_alert=True)


def handle_text(message):
    chat_id = message["chat"]["id"]
    user = message.get("from", {})
    text = (message.get("text") or "").strip().lower()
    if text.startswith("/start"):
        handle_start(message)
    elif text in ("/material", "/materials", "/пакет"):
        if is_subscribed(user.get("id")):
            deliver_material(chat_id, "repeat")
        else:
            send_message(chat_id, "Материал доступен подписчикам канала.",
                         buttons=[BTN_SUB, BTN_CHECK])
    elif text in ("/help", "/помощь"):
        send_message(chat_id, TEXT_HELLO)
    else:
        send_message(chat_id, "Пришлите /start — выдам сборку шаблонов.")


def test_delivery():
    """Сквозная проверка: бот -> проверка подписки -> отправка архива."""
    me = api("getMe")
    print("Бот:", f"@{me.get('username')}")
    if not ADMIN_CHAT_ID:
        print("Не задан ADMIN_CHAT_ID — не знаю, кому отправить архив.")
        return
    state = is_subscribed(ADMIN_CHAT_ID)
    print("Подписка ADMIN_CHAT_ID:", state if state is not None else f"не проверена ({LAST_CHECK_ERROR})")
    if state is False:
        print("Аккаунт не подписан на канал — архив не отправлю.")
        return
    deliver_material(ADMIN_CHAT_ID, "ci-test")
    print("Архив отправлен в личку администратора.")


def check():
    me = api("getMe")
    print("Бот:", f"@{me.get('username')}", "|", me.get("first_name"))
    print("Материал:", MATERIALS_PATH, "—",
          "есть" if os.path.exists(MATERIALS_PATH) else "НЕТ (запустите build_materials.py)")
    target = CHANNEL_ID or CHANNEL_USERNAME
    try:
        api("getChatMember", chat_id=target, user_id=ADMIN_CHAT_ID or me.get("id"))
        print("Канал", target, "— бот видит участников: ок")
    except RuntimeError as e:
        print("Канал", target, "— проверка не прошла:", e)
        print("  -> добавьте бота администратором канала @noroutine2026")
    print("ADMIN_CHAT_ID:", ADMIN_CHAT_ID or "не задан (уведомления о выдаче не придут)")


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
    except OSError as e:
        print("Не удалось сохранить offset:", e)


def main():
    if "--check" in sys.argv:
        check()
        return
    if "--test" in sys.argv:
        test_delivery()
        return
    api("deleteWebhook", drop_pending_updates=False)
    api("getMe")
    deadline = time.time() + RUN_MINUTES * 60 if RUN_MINUTES else None
    print("Бот запущен, жду сообщения..." + (f" (лимит {RUN_MINUTES} мин)" if deadline else ""))
    offset = load_offset()
    if offset:
        print("Продолжаю с offset", offset)
    while True:
        if deadline and time.time() > deadline:
            print("Время работы вышло, сохраняю offset и останавливаюсь.")
            save_offset(offset)
            return
        try:
            updates = api("getUpdates", offset=offset, timeout=POLL_TIMEOUT,
                          allowed_updates=["message", "callback_query"])
            for update in updates:
                offset = update["update_id"] + 1
                save_offset(offset)
                if "callback_query" in update:
                    handle_callback(update["callback_query"])
                elif "message" in update:
                    handle_text(update["message"])
        except requests.exceptions.RequestException as e:
            print("Сеть недоступна, повтор через 5 с:", e)
            time.sleep(5)
        except RuntimeError as e:
            print("Ошибка API:", e)
            time.sleep(3)


if __name__ == "__main__":
    main()
