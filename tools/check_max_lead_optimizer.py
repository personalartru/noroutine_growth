"""Интеграционная проверка «Оптимизатора» в max_lead.py без сети.

Ставит заглушку на MAX API (`call`) и прогоняет user-путь через настоящие
обработчики: выдача архива → клавиатура с «Оптимизатором» под кнопкой заявки →
шаги по кнопкам → шаг с числом сообщением → финал с заявкой владельцу →
отмена и протухание сессии. Проверяет не тексты (этим занимается
simulate_optimizer.py), а обвязку: маршрутизацию callbacks, хранение шага,
пересылку заявки и поведение, когда личка недоступна.

    python3 tools/check_max_lead_optimizer.py
"""
import json
import os
import sys
import tempfile

WORKDIR = tempfile.mkdtemp(prefix="max-lead-test-")
os.chdir(WORKDIR)
os.environ.update({
    "MAX_BOT_TOKEN": "test-token",
    "MAX_CHANNEL_ID": "-71062363105923",
    "MAX_ADMIN_CHAT_ID": "999",
    "MAX_OFFSET_FILE": os.path.join(WORKDIR, ".max_offset"),
    "MAX_PENDING_FILE": os.path.join(WORKDIR, ".max_pending.json"),
    "MAX_DIALOGS_FILE": os.path.join(WORKDIR, ".max_dialogs.json"),
    "MAX_OPTIMIZER_FILE": os.path.join(WORKDIR, ".max_optimizer.json"),
    "MATERIALS_PATH": os.path.join(WORKDIR, "pack.zip"),
})
with open(os.path.join(WORKDIR, "pack.zip"), "wb") as handle:
    handle.write(b"zip")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import max_lead  # noqa: E402

SENT = []


def fake_call(method, path, query=None, body=None):
    SENT.append({"method": method, "path": path, "query": query or {}, "body": body or {}})
    if path == "me":
        return {"username": "se14730534_bot", "name": "No! Routine"}
    return {"ok": True}


max_lead.call = fake_call
max_lead.upload_pack = lambda: "file-token"
max_lead.is_subscribed = lambda user_id: True

USER = 123456
DIALOG = "dialog-123456"
USER2 = 654321              # второй пользователь: проверки, которые портят сессию
DIALOG2 = "dialog-654321"


def reset():
    SENT.clear()


def messages_to(chat=DIALOG):
    return [s for s in SENT if s["path"] == "messages"
            and s["query"].get("chat_id") == chat]


def messages_to_user():
    return messages_to(DIALOG)


def buttons_of(message):
    for attachment in message["body"].get("attachments", []):
        if attachment["type"] == "inline_keyboard":
            return attachment["payload"]["buttons"]
    return []


def texts_to(chat=DIALOG):
    return [m["body"]["text"] for m in messages_to(chat)]


def texts_to_user():
    return texts_to(DIALOG)


def check(label, condition, detail=""):
    print(f"{'✅' if condition else '❌'} {label}" + (f" — {detail}" if detail else ""))
    return bool(condition)


results = []

# 1. /start в диалоге: архив и клавиатура «заявка → оптимизатор»
reset()
max_lead.remember_dialog(USER, DIALOG)
max_lead.handle_text(USER, DIALOG, None, "dialog", "Павел", "personartru", "/start")
archive = [m for m in messages_to_user()
           if any(b.get("payload") == "want_task" for row in buttons_of(m)
                  for b in row)]
ok = check("архив выдан с клавиатурой", len(archive) == 1)
results.append(ok)
if archive:
    flat = [b.get("payload") for row in buttons_of(archive[0]) for b in row]
    order = [p for p in flat if p in ("want_task", "opt:start")]
    results.append(check("«Оптимизатор» идёт сразу под кнопкой заявки",
                         order == ["want_task", "opt:start"], str(order)))

# 2. Кнопка «Оптимизатор» → шаг 1 с шестью сферами
reset()
max_lead.handle_callback({"payload": "opt:start", "callback_id": "cb1",
                          "user": {"user_id": USER, "name": "Павел"}})
texts = texts_to_user()
results.append(check("открыт шаг «сфера»", any("Шаг 1 из 6" in t for t in texts),
                     f"{len(texts)} сообщ."))
session = json.load(open(os.environ["MAX_OPTIMIZER_FILE"]))[str(USER)]
results.append(check("шаг сохранён в файл состояния", session["step"] == "sphere",
                     session["step"]))

# 3. Полный путь по кнопкам до финала
flow = ["opt:s:support", "opt:m:team", "opt:r:0", "opt:r:1", "opt:r:ok",
        "opt:c:8", "opt:c:4",
        "opt:o:tickets", "opt:o:status", "opt:o:ok", "opt:t:chat", "opt:t:n8n",
        "opt:t:ok", "opt:t:plan"]
reset()
for payload in flow:
    max_lead.handle_callback({"payload": payload, "callback_id": "cb",
                              "user": {"user_id": USER, "name": "Павел"}})
texts = texts_to_user()
results.append(check("есть часы и стоимость рутины",
                     any("Часы рутины" in t for t in texts)))
results.append(check("есть экономия", any("Экономия" in t for t in texts)))
results.append(check("есть чек-лист внедрения",
                     any("Пошаговый чек-лист" in t for t in texts)))
results.append(check("есть бюджет и дисклеймер",
                     any("Примерный бюджет" in t for t in texts)
                     and any("Дисклеймер" in t for t in texts)))
final = next((m for m in messages_to_user()
              if any(b.get("payload") == "opt:fb" for row in buttons_of(m)
                     for b in row)), None)
results.append(check("в финале кнопка обратной связи", final is not None))

# 3b. Регресс на прод-сбой: на шаге «сколько таких человек» кнопки обязаны быть
#     полноценными (type=callback) — без type MAX клавиатуру не показывает.
reset()
max_lead.remember_dialog(USER2, DIALOG2)
for payload in ("opt:start", "opt:s:hr", "opt:m:team", "opt:r:2", "opt:r:ok"):
    max_lead.handle_callback({"payload": payload, "callback_id": "cb",
                              "user": {"user_id": USER2}})
count_kb = [row for m in messages_to(DIALOG2) for row in buttons_of(m)
            if any(b.get("payload") == "opt:c:1" for b in row)]
labels = [b["text"] for row in count_kb for b in row]
results.append(check("есть кнопки 1–5 на вопросе о количестве",
                     all(str(i) in labels for i in range(1, 6)), str(labels)))
results.append(check("у всех кнопок клавиатуры есть type",
                     all(b.get("type") == "callback" for row in count_kb for b in row),
                     str(count_kb[:1])))
results.append(check("роль в опросе — отмеченная",
                     any("Онбординг-менеджер" in t for t in texts_to(DIALOG2))))

# 4. Обратная связь: текст уходит владельцу, сессия закрывается
reset()
max_lead.handle_callback({"payload": "opt:fb", "callback_id": "cb",
                          "user": {"user_id": USER, "name": "Павел"}})
max_lead.handle_text(USER, DIALOG, None, "dialog", "Павел", "personartru",
                     "Хочу автоматизировать тикеты, 8 человек")
admin = [s for s in SENT if s["query"].get("chat_id") == "999"]
results.append(check("заявка ушла владельцу", len(admin) == 1))
if admin:
    body = admin[0]["body"]["text"]
    results.append(check("в заявке есть текст и черновик расчёта",
                         "автоматизировать тикеты" in body
                         and "[Оптимизатор]" in body and "Поддержка" in body))
results.append(check("сессия очищена после заявки",
                     str(USER) not in json.load(
                         open(os.environ["MAX_OPTIMIZER_FILE"]))))

# 5. Свободный текст на шаге «своё число» не превращается в лид
reset()
max_lead.handle_callback({"payload": "opt:start", "callback_id": "cb",
                          "user": {"user_id": USER}})
max_lead.handle_callback({"payload": "opt:s:hr", "callback_id": "cb",
                          "user": {"user_id": USER}})
max_lead.handle_callback({"payload": "opt:m:team", "callback_id": "cb",
                          "user": {"user_id": USER}})
for payload in ("opt:r:0", "opt:r:1", "opt:r:ok", "opt:c:3", "opt:c:x"):
    max_lead.handle_callback({"payload": payload, "callback_id": "cb",
                              "user": {"user_id": USER}})
reset()
max_lead.handle_text(USER, DIALOG, None, "dialog", "Павел", "personartru", "42")
results.append(check("число попало в расчёт, а не в заявку",
                     not any(s["query"].get("chat_id") == "999" for s in SENT)))
session = json.load(open(os.environ["MAX_OPTIMIZER_FILE"]))[str(USER)]
results.append(check("количество по второй роли принялось",
                     session["last_role"].endswith("× 42"),
                     session.get("last_role", "")))
results.append(check("первая роль осталась в команде",
                     any(r["label"].startswith("Рекрутер") and r["count"] == 3
                         for r in session["roles"]),
                     str(session["roles"])))

# 6. «отмена» закрывает сессию
reset()
max_lead.handle_text(USER, DIALOG, None, "dialog", "Павел", "personartru", "отмена")
results.append(check("отмена работает", str(USER) not in json.load(
    open(os.environ["MAX_OPTIMIZER_FILE"]))))

# 7. Личка недоступна → ответ на callback, а не потерянный клик
reset()
_real_send_direct = max_lead.send_direct
max_lead.send_direct = lambda *a, **kw: False
max_lead.handle_callback({"payload": "opt:start", "callback_id": "cb7",
                          "user": {"user_id": 777}})
max_lead.send_direct = _real_send_direct
answers = [s for s in SENT if s["path"] == "answers"]
results.append(check("без доступной лички клик не теряется", len(answers) >= 1,
                     f"ответов на callback: {len(answers)}"))

# 8. Просроченная сессия не перехватывает обычные сообщения
import optimizer  # noqa: E402

session = optimizer.new_session()
session["step"] = "feedback"
session["updated"] -= optimizer.SESSION_TTL + 60
store = json.load(open(os.environ["MAX_OPTIMIZER_FILE"]))
store[str(USER)] = session
json.dump(store, open(os.environ["MAX_OPTIMIZER_FILE"], "w"), ensure_ascii=False)
reset()
max_lead.handle_text(USER, DIALOG, None, "dialog", "Павел", "personartru",
                     "напишите мне по автоматизации")
results.append(check("просроченная сессия отдала текст в лид-заявку",
                     any(s["query"].get("chat_id") == "999" for s in SENT)))

print(f"\n{sum(results)}/{len(results)} проверок пройдено")
sys.exit(0 if all(results) else 1)
