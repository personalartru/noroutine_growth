"""Проверка `max_lead.py` после вырезания «Оптимизатора» — без сети и токена.

Ставит заглушку на MAX API (`call`, `upload_pack`, `is_subscribed`) и прогоняет
лид-сценарий через настоящие обработчики: выдача архива, «Хочу такое же под
свой процесс», проверка подписки, заявка любым текстом. Отдельно проверяет то,
ради чего написан этот файл: кнопки «Оптимизатор» в клавиатурах больше нет, а
устаревшие нажатия `opt:` и слова «оптимизатор» / «отмена» не молчат и не
превращаются в лид — они ведут в отдельного бота @se14730534_1_bot.

    python3 tools/check_max_lead.py
"""
import json
import os
import sys
import tempfile

WORKDIR = tempfile.mkdtemp(prefix="max-lead-check-")
os.chdir(WORKDIR)
os.environ.update({
    "MAX_BOT_TOKEN": "test-token",
    "MAX_CHANNEL_ID": "-71062363105923",
    "MAX_ADMIN_CHAT_ID": "999",
    "OFFSET_FILE": os.path.join(WORKDIR, ".offset"),
    "MAX_OFFSET_FILE": os.path.join(WORKDIR, ".max_offset"),
    "MAX_PENDING_FILE": os.path.join(WORKDIR, ".max_pending.json"),
    "MAX_DIALOGS_FILE": os.path.join(WORKDIR, ".max_dialogs.json"),
    "MAX_COMMENT_CHAT_FILE": os.path.join(WORKDIR, ".max_comment_chat"),
    "MATERIALS_PATH": os.path.join(WORKDIR, "pack.zip"),
})
with open(os.path.join(WORKDIR, "pack.zip"), "wb") as handle:
    handle.write(b"zip")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import max_lead  # noqa: E402

SENT = []


def fake_call(method, path, query=None, body=None):
    SENT.append({"method": method, "path": path, "query": query or {},
                 "body": body or {}})
    if path == "me":
        return {"username": "se14730534_bot", "name": "No! Routine"}
    return {"ok": True}


max_lead.call = fake_call
max_lead.upload_pack = lambda: "file-token"
max_lead.is_subscribed = lambda user_id: True

USER = 123456
DIALOG = "dialog-123456"
ADMIN = "999"
OPT_BOT = "https://max.ru/se14730534_1_bot"


def reset():
    del SENT[:]


def messages_to(chat):
    return [s for s in SENT if s["path"] == "messages"
            and s["query"].get("chat_id") == chat]


def texts_to(chat):
    return [m["body"]["text"] for m in messages_to(chat)]


def buttons_of(message):
    for attachment in message["body"].get("attachments", []):
        if attachment["type"] == "inline_keyboard":
            return attachment["payload"]["buttons"]
    return []


def all_buttons(chat):
    return [b for m in messages_to(chat) for row in buttons_of(m) for b in row]


def click(payload, callback_id="cb"):
    max_lead.handle_callback({"payload": payload, "callback_id": callback_id,
                              "user": {"user_id": USER, "name": "Павел",
                                       "username": "personartru"}})


def say(text):
    max_lead.handle_text(USER, DIALOG, None, "dialog", "Павел", "personartru", text)


def check(label, condition, detail=""):
    print(f"{'✅' if condition else '❌'} {label}" + (f" — {detail}" if detail else ""))
    return bool(condition)


results = []

# 1. /start подписанному: архив и одна кнопка заявки — без «Оптимизатора»
reset()
max_lead.remember_dialog(USER, DIALOG)
say("/start")
results.append(check("архив выдан с файлом",
                     any(a["type"] == "file" for m in messages_to(DIALOG)
                         for a in m["body"].get("attachments", []))))
results.append(check("кнопка «Оптимизатор» из клавиатуры ушла",
                     not any((b.get("text") or "").startswith("Оптимизатор")
                             for b in all_buttons(DIALOG)),
                     str([b.get("text") for b in all_buttons(DIALOG)])))
results.append(check("в клавиатурах нет callback'ов opt:",
                     not any((b.get("payload") or "").startswith("opt:")
                             for b in all_buttons(DIALOG))))
results.append(check("кнопка заявки осталась",
                     any(b.get("payload") == "want_task" for b in all_buttons(DIALOG))))
results.append(check("у каждой кнопки есть type",
                     all(b.get("type") in ("callback", "link")
                         for b in all_buttons(DIALOG))))

# 2. «Хочу такое же под свой процесс» → просьба описать задачу
reset()
click("want_task")
results.append(check("want_task отвечает просьбой о задаче",
                     any("Опишите задачу" in t for t in texts_to(DIALOG))))

# 3. «Я подписался» → архив
reset()
click("check_sub")
results.append(check("check_sub выдаёт архив",
                     any(a["type"] == "file" for m in messages_to(DIALOG)
                         for a in m["body"].get("attachments", []))))

# 4. Устаревшая кнопка opt: → указатель на отдельного бота, не заявка
reset()
click("opt:s:it", callback_id="cb-old")
results.append(check("opt:-клик ведёт в нового бота",
                     any(OPT_BOT in t for t in texts_to(DIALOG)),
                     str(texts_to(DIALOG))[:120]))
results.append(check("opt:-клик даёт ссылку, а не callback",
                     any(b.get("url") == OPT_BOT for b in all_buttons(DIALOG))))
results.append(check("opt:-клик не стал лидом (заявок владельцу: 0)",
                     not messages_to(ADMIN)))

# 5. Личка недоступна → нажатие не теряется, отвечаем на callback
reset()
real_send_direct = max_lead.send_direct
max_lead.send_direct = lambda *a, **k: False
click("opt:again", callback_id="cb-no-personal")
max_lead.send_direct = real_send_direct
answers = [s for s in SENT if s["path"] == "answers"]
results.append(check("без лички opt:-клик получает ответ на callback",
                     len(answers) == 1 and "se14730534_1_bot" in
                     answers[0]["body"]["message"]["text"],
                     str([a["body"]["message"]["text"][:40] for a in answers])))

# 6. Слова про оптимизатор и «отмена» прежнего расчёта → указатель, не лид
for word in ("оптимизатор", "калькулятор", "расчёт", "посчитай", "отмена", "стоп"):
    reset()
    say(word)
    results.append(check(f"слово «{word}» → указатель, не заявка",
                         any(OPT_BOT in t for t in texts_to(DIALOG))
                         and not messages_to(ADMIN)))

# 7. Обычный текст по-прежнему становится заявкой
reset()
say("Нужна автоматизация приёма заявок из форм")
results.append(check("текст ушёл владельцу как заявка",
                     any("Нужна автоматизация" in t and "Павел" in t
                         for t in texts_to(ADMIN)),
                     str(texts_to(ADMIN))[:120]))
results.append(check("пользователь получил подтверждение и архив",
                     any("Принял запрос" in t for t in texts_to(DIALOG))
                     and any(a["type"] == "file" for m in messages_to(DIALOG)
                             for a in m["body"].get("attachments", []))))

# 8. /help работает, состояние оптимизатора больше не пишется
reset()
say("/help")
results.append(check("/help отвечает приветствием",
                     any("бот канала" in t for t in texts_to(DIALOG))))
results.append(check("файла состояния оптимизатора не появляется",
                     not os.path.exists(os.path.join(WORKDIR, ".max_optimizer.json"))))
results.append(check("модуль optimizer.py удалён из репозитория",
                     not os.path.exists(os.path.join(ROOT, "optimizer.py"))))
results.append(check("в max_lead.py нет импорта optimizer",
                     "import optimizer" not in
                     open(os.path.join(ROOT, "max_lead.py"), encoding="utf-8").read()))

failed = sum(1 for r in results if not r)
print(f"\n{len(results) - failed}/{len(results)} проверок пройдено")
sys.exit(1 if failed else 0)
